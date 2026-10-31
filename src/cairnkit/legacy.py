"""Clean what 0.3.1 left in a memory. Runs at most once, and each step is safe to repeat.

0.3.1 mined commits and stored text that passed a quality gate as long-term facts. A fact must
come from an agent's judgment, so those facts end here. They stay in the archive.
"""

from __future__ import annotations

import contextlib
import json

from cairnkit.autotidy import WRITER, Retirement, write_log
from cairnkit.clock import now, stamp
from cairnkit.memory import Memory
from cairnkit.store import append_records

CANDIDATE_FILE = "proposals/auto-candidates.jsonl"
LEFTOVERS = (
    "proposals/stale-pending.md",
    ".autogate-state.json",
    ".autogate.lock",
    ".auto-candidates.lock",
)
REASON = "Mined from a commit by 0.3.1; no agent chose to write it."


def _mined_ids(text: str) -> set[str]:
    found = set()
    for line in text.splitlines():
        with contextlib.suppress(ValueError):
            record = json.loads(line)
            if isinstance(record, dict) and record.get("fact_id"):
                found.add(str(record["fact_id"]))
    return found


def clean(memory: Memory) -> list[str]:
    """End the facts that 0.3.1 mined. Remove its files. Return the ended ids."""
    path = memory.dir / CANDIDATE_FILE
    ended: list[Retirement] = []
    if path.exists():
        mined = _mined_ids(path.read_text(encoding="utf-8"))
        for fact_id in sorted(mined):
            state = memory.states.get(fact_id)
            if not state or state.get("status") != "active" or state.get("pinned"):
                continue
            if state.get("basis") == "told" or state.get("kind") == "rule":
                continue
            ended.append(Retirement(fact_id, "mined", "expired", REASON))
        if ended:
            at = stamp(now())
            append_records(memory.writer_file(WRITER), [item.record(at) for item in ended])
            write_log(memory, ended, at)
            memory.reload()
    for rel in (CANDIDATE_FILE, *LEFTOVERS):
        with contextlib.suppress(OSError):
            (memory.dir / rel).unlink()
    return [item.id for item in ended]
