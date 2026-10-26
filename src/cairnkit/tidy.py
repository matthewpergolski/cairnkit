"""`memory tidy`: propose clean-up changes (no AI). A person approves each one.

`memory tidy` writes proposals to `proposals/<date>.md` and changes no fact.
`memory tidy --apply ID...` writes the change records of the approved
proposals only. Proposal ids come from their content, so they stay the same
between runs while the facts stay the same.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from cairnkit import followups, markers
from cairnkit.autotidy import outranks
from cairnkit.clock import now, parse_time, stamp
from cairnkit.memory import Memory
from cairnkit.paths import merged_checker
from cairnkit.schema import validate_record
from cairnkit.similar import exact_key
from cairnkit.state import effective_status
from cairnkit.store import append_records

RULE_KINDS = ("trap", "preference")
RULE_AGE_DAYS = 30
RULES_START = "<!-- cairnkit:rules:start -->"
RULES_END = "<!-- cairnkit:rules:end -->"
# The markers before the rename. A block found with them gets the new markers.
OLD_RULES = ("<!-- project-memory:rules:start -->", "<!-- project-memory:rules:end -->")
RULES_PAIRS = ((RULES_START, RULES_END), OLD_RULES)
WRITER = "tidy"


@dataclass
class Proposal:
    kind: str
    summary: str
    changes: list[dict]
    rule_text: str | None = None
    id: str = field(init=False)

    def __post_init__(self) -> None:
        key = json.dumps([self.kind, self.changes, self.rule_text], sort_keys=True)
        self.id = "p-" + hashlib.sha1(key.encode()).hexdigest()[:6]


def _age_days(state: dict, moment) -> float:
    try:
        return (moment - parse_time(state["learned_at"])).total_seconds() / 86400
    except (KeyError, ValueError):
        return 0.0


def _duplicates(active: list[dict]) -> list[Proposal]:
    """Exact repeats only. A near repeat is a flagged pair, which an agent task handles."""
    out = []
    ordered = sorted(active, key=lambda s: (s.get("learned_at", ""), s["id"]))
    toks = {s["id"]: exact_key(s.get("text", "")) for s in ordered}
    done: set[str] = set()
    for i, older in enumerate(ordered):
        if older["id"] in done:
            continue
        for newer in ordered[i + 1 :]:
            if newer["id"] in done or not toks[older["id"]][0]:
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
                        f"{older['id']} repeats {newer['id']} (exact): {older.get('text')}",
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


def build_proposals(memory: Memory, days: int) -> list[Proposal]:
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
                text = f"{state['id']} is pinned but ended: {reason}"
                proposals.append(Proposal("pinned-expired", text, [change]))

    proposals += _chains(states)

    linked = {link["id"] for s in states.values() for link in s.get("links", [])}
    linked |= {s["id"] for s in states.values() if s.get("links")}
    rules_file = memory.config.get("rules_file", "AGENTS.md")
    for state in sorted(active, key=lambda s: s["id"]):
        if state.get("scope", "long") != "long":
            continue
        age = _age_days(state, moment)
        if age > days and state["id"] not in linked and not state.get("pinned"):
            change = {
                "id": state["id"],
                "status": "expired",
                "reason": f"Stale: older than {days} days, no links. Confirmed by review.",
            }
            proposals.append(
                Proposal("stale", f"{state['id']} ({int(age)} days): {state.get('text')}", [change])
            )
        durable = state.get("kind") in RULE_KINDS and state.get("basis") != "guess"
        if state.get("pinned") or (durable and age >= RULE_AGE_DAYS):
            change = {
                "id": state["id"],
                "status": "promoted",
                "held_by": rules_file,
                "reason": f"Moved into the shared rules file {rules_file}.",
            }
            proposals.append(
                Proposal(
                    "rule",
                    f"{state['id']} -> {rules_file}: {state.get('text')}",
                    [change],
                    rule_text=state.get("text"),
                )
            )
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
    lines += ["", "Approve with: `memory tidy --apply ID [ID ...]`.", ""]
    path.write_text("\n".join(lines))
    return str(path)


def rules_block_broken(path) -> bool:
    """True when the rules file has a lost marker, two blocks, or an old and a new block."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    return markers.find(old, RULES_PAIRS)[0] == "broken"


def add_rule(path, text: str) -> bool:
    """Add one rule line inside the marked rules block. Text outside it stays.

    An old block gets the new markers in place. A broken block changes nothing:
    return False.
    """
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    found, (start_mark, end_mark) = markers.find(before, RULES_PAIRS)
    if found == "broken":
        return False
    old = before.replace(start_mark, RULES_START).replace(end_mark, RULES_END)
    line = f"- {text}\n"
    if found == "ok":
        start, end = old.find(RULES_START), old.find(RULES_END)
        if line in old[start:end] and old == before:
            return True
        new = old if line in old[start:end] else old[:end] + line + old[end:]
    else:
        sep = "" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
        block = f"{RULES_START}\n## Rules learned from project memory\n\n{line}{RULES_END}\n"
        new = old + sep + block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new)
    return True


def run_tidy(memory: Memory, days: int, apply: list[str] | None) -> int:
    proposals = build_proposals(memory, days)
    if not apply:
        report = write_report(memory, proposals)
        for p in proposals:
            print(f"- {p.id} [{p.kind}] {p.summary}")
        print(f"{len(proposals)} proposal(s). Report: {report}")
        if proposals:
            print("A person approves: `memory tidy --apply ID [ID ...]`.")
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
    rule_files = [
        (memory.project.root / by_id[pid].changes[0]["held_by"], by_id[pid].rule_text)
        for pid in apply
        if by_id[pid].rule_text
    ]
    for path, _ in rule_files:
        if rules_block_broken(path):
            print(markers.broken_message(path, "memory tidy --apply"))
            return 1
    for path, text in rule_files:
        add_rule(path, text)
    append_records(memory.writer_file(WRITER), records)
    print(f"applied {len(apply)} proposal(s): {len(records)} change record(s)")
    return 0
