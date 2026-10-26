"""Default rule facts (the commits preset) and the commit-msg guard sync."""

from __future__ import annotations

from cairnkit.clock import now, stamp
from cairnkit.githook import GUARD_REF
from cairnkit.presets import DEFAULT, load_preset
from cairnkit.store import append_records

WRITER = "default"
# The rules of the commits preset (preset_data/commits.toml), in order.
DEFAULT_RULES = [rule.text for rule in load_preset(DEFAULT).rules]

# The commit-msg guard checks this rule in full. The other default rules also
# cover pull requests, docs and wording, which no hook can check.
GUARDED = DEFAULT_RULES[0]


def sync_guard(memory, guarded: bool) -> list[str]:
    """Mark the guarded default rule enforced or advisory, to match the installed guard.

    It writes a change record (append only). It never changes a value set by a person.
    """
    from cairnkit.schema import validate_record

    want = GUARD_REF if guarded else None
    steps, records = [], []
    for state in memory.states.values():
        if state.get("source") != "default" or state.get("text") != GUARDED:
            continue
        have = state.get("enforced_by")
        if state.get("status") != "active" or have == want or have not in (None, GUARD_REF):
            continue
        reason = "The commit-msg guard is installed." if want else "No commit-msg guard."
        records.append(
            {
                "type": "change",
                "id": state["id"],
                "at": stamp(now()),
                "enforced_by": want,
                "reason": reason,
                "writer": WRITER,
            }
        )
        steps.append(f"mark rule {state['id']} " + (f"enforced by {want}" if want else "advisory"))
    problems = [p for r in records for p in validate_record(r)]
    if problems:
        raise ValueError("; ".join(problems))
    if records:
        append_records(memory.writer_file(WRITER), records)
    return steps
