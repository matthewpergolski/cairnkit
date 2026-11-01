"""`memory tidy`: list clean-up changes (no AI). An agent decides.

`memory tidy` writes proposals to `proposals/<date>.md` and changes no fact.
`memory tidy --apply ID...` writes the change records of the chosen
proposals only. Proposal ids come from their content, so they stay the same
between runs while the facts stay the same.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from cairnkit import followups
from cairnkit.autotidy import outranks, print_unknown
from cairnkit.clock import now, stamp
from cairnkit.memory import Memory
from cairnkit.paths import merged_checker
from cairnkit.schema import validate_record
from cairnkit.selection import clean
from cairnkit.similar import repeat_key
from cairnkit.state import effective_status
from cairnkit.store import append_records

WRITER = "tidy"


@dataclass
class Proposal:
    kind: str
    summary: str
    changes: list[dict]
    id: str = field(init=False)

    def __post_init__(self) -> None:
        key = json.dumps([self.kind, self.changes], sort_keys=True)
        self.id = "p-" + hashlib.sha1(key.encode()).hexdigest()[:6]


def _duplicates(active: list[dict]) -> list[Proposal]:
    """Exact repeats only. A near repeat is a flagged pair, which an agent task handles."""
    out = []
    ordered = sorted(active, key=lambda s: (s.get("learned_at", ""), s["id"]))
    toks = {s["id"]: repeat_key(s.get("text", "")) for s in ordered}
    done: set[str] = set()
    for i, older in enumerate(ordered):
        if older["id"] in done:
            continue
        for newer in ordered[i + 1 :]:
            if newer["id"] in done or not toks[older["id"]]:
                continue
            if toks[older["id"]] == toks[newer["id"]] and not outranks(older, newer):
                change = {
                    "id": older["id"],
                    "status": "superseded",
                    "superseded_by": newer["id"],
                    "reason": f"Duplicate of {newer['id']} (exact match).",
                }
                out.append(
                    Proposal(
                        "duplicate",
                        clean(f"{older['id']} repeats {newer['id']} (exact): {older.get('text')}"),
                        [change],
                    )
                )
                done.add(older["id"])
                break
    return out


def _chains(states: dict[str, dict]) -> list[Proposal]:
    out = []
    for state in states.values():
        if state.get("status") != "superseded" or not state.get("superseded_by"):
            continue
        path, current = [state["id"]], states.get(state["superseded_by"])
        while current and current.get("status") == "superseded" and current["id"] not in path:
            path.append(current["id"])
            current = states.get(current.get("superseded_by", ""))
        if len(path) > 1 and current and current.get("status") == "active":
            change = {
                "id": state["id"],
                "status": "superseded",
                "superseded_by": current["id"],
                "reason": f"Superseded chain {' -> '.join(path)} -> {current['id']}.",
            }
            out.append(Proposal("chain", f"{state['id']} -> ... -> {current['id']}", [change]))
    return out


def build_proposals(memory: Memory) -> list[Proposal]:
    moment = now()
    is_merged = merged_checker(memory.project.root)
    states = {k: v for k, v in memory.states.items() if v.get("status") != "purged"}
    status = {k: effective_status(v, moment, is_merged) for k, v in states.items()}
    active = [s for s in states.values() if status[s["id"]][0] == "active"]
    proposals = _duplicates(active)

    for state in states.values():
        if state.get("pinned") and state.get("status") == "active":
            computed, reason = status[state["id"]]
            if computed == "expired":
                change = {"id": state["id"], "status": "expired", "reason": reason}
                text = clean(f"{state['id']} is pinned but ended: {reason}")
                proposals.append(Proposal("pinned-expired", text, [change]))

    proposals += _chains(states)

    return proposals


def write_report(memory: Memory, proposals: list[Proposal]) -> str:
    folder = memory.dir / "proposals"
    folder.mkdir(exist_ok=True)
    path = folder / f"{now().date().isoformat()}.md"
    lines = [f"# Tidy proposals, {stamp(now())}", ""]
    if not proposals:
        lines.append("Nothing to propose.")
    for p in proposals:
        lines.append(f"- {p.id} [{p.kind}] {p.summary}")
    lines += ["", "To apply: `memory tidy --apply ID [ID ...]`.", ""]
    path.write_text("\n".join(lines))
    return str(path)


def run_tidy(memory: Memory, apply: list[str] | None) -> int:
    proposals = build_proposals(memory)
    if not apply:
        report = write_report(memory, proposals)
        for p in proposals:
            print(f"- {p.id} [{p.kind}] {p.summary}")
        print(f"{len(proposals)} proposal(s). Report: {report}")
        print_unknown(memory)
        if proposals:
            print("To apply: `memory tidy --apply ID [ID ...]`.")
        followups.refresh(memory)
        pairs = len(followups.open_pairs(memory))
        items = len(followups.open_items(memory))
        print(
            f"Open similar pairs: {pairs}"
            + (f". An agent task lists them: {followups.TASK_PATH}" if pairs else "")
        )
        if items:
            print(f"Open follow-up items: {items}. See {followups.TASK_PATH}")
        return 0
    by_id = {p.id: p for p in proposals}
    unknown = [pid for pid in apply if pid not in by_id]
    if unknown:
        print(f"error: not a current proposal: {', '.join(unknown)}. Run `memory tidy` again.")
        return 1
    moment = stamp(now())
    records = []
    for pid in apply:
        for change in by_id[pid].changes:
            record = {"type": "change", **change, "at": moment, "writer": WRITER}
            problems = validate_record(record)
            if problems:
                print(f"error: {pid}: {'; '.join(problems)}")
                return 1
            records.append(record)
    append_records(memory.writer_file(WRITER), records)
    print(f"applied {len(apply)} proposal(s): {len(records)} change record(s)")
    return 0
