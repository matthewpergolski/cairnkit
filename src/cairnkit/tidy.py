"""`memory tidy`: list clean-up changes (no AI). An agent decides.

`memory tidy` writes proposals to `proposals/<date>.md` and changes no fact.
`memory tidy --apply ID...` writes the change records of the chosen
proposals only. Proposal ids come from their content, so they stay the same
between runs while the facts stay the same.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from cairnkit import followups, landed, plainfile
from cairnkit.autotidy import SNIPPET, outranks, print_unknown
from cairnkit.clock import now, stamp
from cairnkit.memory import Memory
from cairnkit.paths import merged_checker
from cairnkit.schema import validate_record
from cairnkit.selection import clean, clean_path, person_said
from cairnkit.similar import repeat_key
from cairnkit.skills import running_tool
from cairnkit.state import effective_status
from cairnkit.store import append_records

WRITER = "tidy"


@dataclass
class Proposal:
    kind: str
    summary: str
    changes: list[dict]
    # A person stated the fact: the owner ends it, and `--apply` does not.
    ask: bool = False
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


NAMED = 5
ASK_OWNER = "A person stated it, so ask the owner before you end it."
_REPLACES = re.compile(r"(?i)\b(?:replaces?|supersedes?|instead of|overrides?|no longer)\b")


def _snippet(state: dict) -> str:
    return " ".join(str(state.get("text", "")).split())[:SNIPPET]


def landed_work(
    memory: Memory, active: list[dict], patient: bool = False
) -> dict[str, landed.Landed]:
    """The active one-time approvals whose work landed, by id. `memory tidy` is patient."""
    done = landed.find(memory, patient=patient)
    return {s["id"]: done[s["id"]] for s in active if s["id"] in done}


def _landed(memory: Memory, active: list[dict]) -> list[Proposal]:
    """The agent decides: the work landed, but a rule can still hold after it."""
    by_id = {s["id"]: s for s in active}
    out = []
    for fid, work in sorted(landed_work(memory, active, patient=True).items()):
        reason = f"Work landed in {work.commit} on {work.date}."
        ask = person_said(by_id[fid])
        end = (
            f"{ASK_OWNER} If the owner agrees, end it: memory change"
            if ask
            else "End it: memory change"
        )
        summary = clean(
            f"{fid} ({by_id[fid].get('kind')}, {_snippet(by_id[fid])!r}): its work landed in "
            f"{work.commit} on {work.date} ({work.subject!r}). {end} {fid} "
            f'--status expired --reason "{reason}" If it still holds: memory change {fid} '
            f'--status active --reason "Still holds after {work.commit}."'
        )
        change = {"id": fid, "status": "expired", "reason": reason}
        out.append(Proposal("landed", summary, [change], ask=ask))
    return out


def _replaced_in_words(active: list[dict]) -> list[Proposal]:
    """A newer fact says, by id, that it replaces an active rule, and no link ends that rule."""
    rules = [s for s in active if s.get("kind") == "rule"]
    out = []
    for new in active:
        text = str(new.get("text", ""))
        if not _REPLACES.search(text):
            continue
        for old in rules:
            newer = str(new.get("learned_at", "")) > str(old.get("learned_at", ""))
            if old["id"] not in text or not newer or outranks(old, new):
                continue
            change = {
                "id": old["id"],
                "status": "superseded",
                "superseded_by": new["id"],
                "reason": f"{new['id']} says that it replaces {old['id']}.",
            }
            summary = clean(f"{new['id']} says that it replaces {old['id']}: {_snippet(old)!r}")
            out.append(Proposal("replaced-in-words", summary, [change]))
    return out


def landed_line(memory: Memory) -> str | None:
    """One session-start line that names the rules and decisions whose work landed. Ids only,
    because this line is outside the frame of stored notes."""
    moment, is_merged = now(), merged_checker(memory.project.root)
    active = [
        s for s in memory.states.values() if effective_status(s, moment, is_merged)[0] == "active"
    ]
    work = sorted(landed_work(memory, active))
    if not work:
        return None
    by_id = {s["id"]: s for s in active}
    told = [fid for fid in work if person_said(by_id[fid])]
    return (
        f"memory: the work of {len(work)} one-time approval(s) landed on the main branch: "
        f"{_listed(work)}. `memory tidy` shows each commit, and the command to end it or keep "
        f"it.{landed.ask_note(told, len(work))}"
    )


def _listed(ids: list[str]) -> str:
    return ", ".join(ids[:NAMED]) + (f" and {len(ids) - NAMED} more" if len(ids) > NAMED else "")


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
    proposals += _landed(memory, active)
    proposals += _replaced_in_words(active)
    return proposals


def write_report(memory: Memory, proposals: list[Proposal]) -> str:
    folder = plainfile.inside(memory.dir, memory.dir / "proposals")
    folder.mkdir(exist_ok=True)
    path = folder / f"{now().date().isoformat()}.md"
    lines = [f"# Tidy proposals, {stamp(now())}", ""]
    if not proposals:
        lines.append("Nothing to propose.")
    for p in proposals:
        lines.append(f"- {p.id} [{p.kind}] {p.summary}")
    lines += ["", "To apply: `memory tidy --apply ID [ID ...]`.", ""]
    plainfile.write_text(plainfile.inside(memory.dir, path), "\n".join(lines))
    return str(path)


def run_tidy(memory: Memory, apply: list[str] | None) -> int:
    proposals = build_proposals(memory)
    if not apply:
        report = write_report(memory, proposals)
        for p in proposals:
            print(f"- {p.id} [{p.kind}] {p.summary}")
        print(f"{len(proposals)} proposal(s). Report: {clean_path(report)}")
        print_unknown(memory)
        if proposals:
            print("To apply: `memory tidy --apply ID [ID ...]`.")
        followups.refresh(memory)
        pairs = len(followups.open_pairs(memory))
        items = len(followups.open_items(memory))
        print(
            f"Open similar pairs: {pairs}"
            + (" (the list stops there)" if pairs >= followups.MAX_PAIRS else "")
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
    chosen = []
    for pid in apply:
        if by_id[pid].ask and running_tool():
            ids = ", ".join(change["id"] for change in by_id[pid].changes)
            print(
                f"skipped {pid}: a person stated {ids}, so ask the owner. If the owner agrees, run "
                "the `memory change` command that `memory tidy` shows."
            )
            continue
        chosen.append(pid)
        for change in by_id[pid].changes:
            record = {"type": "change", **change, "at": moment, "writer": WRITER}
            problems = validate_record(record)
            if problems:
                print(f"error: {pid}: {'; '.join(problems)}")
                return 1
            records.append(record)
    if records:
        append_records(memory.writer_file(WRITER), records, root=memory.dir)
    print(f"applied {len(chosen)} proposal(s): {len(records)} change record(s)")
    return 0
