"""Clean what 0.3.1 left in a memory. Runs at most once, and each step is safe to repeat.

0.3.1 mined commits and stored text that passed a quality gate as long-term facts. A fact must
come from an agent's judgment, so those facts end here. They stay in the archive.

A false end is worse than a stale fact, so a fact ends only with proof that the gate wrote it. The
fact is exactly what the gate writes for its candidate, and the candidate could pass the gate.
`memory candidates accept` and a `memory add` of the same words write the same lines, with one
difference: the time between them. A real run of tag v0.3.1 shows it. The post-commit and pre-push
hooks drafted a candidate and ran the gate in one process, under a limit of 1 and 3 seconds, so the
decision came inside HOOK_SECONDS of the draft. A person or an agent must read the candidate first.

This compares two times that 0.3.1 recorded. It does not read the clock or the age of a fact.

What it leaves: a mined fact that a later gate run accepted, at a session start. Nothing proves who
accepted that one, so it stays. It is a mined line with basis `guess`.
"""

from __future__ import annotations

import contextlib
import json

from cairnkit.autotidy import WRITER, Retirement, write_log
from cairnkit.clock import now, parse_time, stamp
from cairnkit.memory import Memory
from cairnkit.store import append_records

CANDIDATE_FILE = "proposals/auto-candidates.jsonl"
GATE_BASIS = "guess"
GATE_KINDS = ("lesson", "decision", "trap")
GATE_SOURCES = ("commit:", "file:")
GATE_TEXT_LENGTH = range(40, 501)
LEFTOVERS = (
    "proposals/stale-pending.md",
    ".autogate-state.json",
    ".autogate.lock",
    ".auto-candidates.lock",
)
REASON = "Mined from a commit by 0.3.1; no agent chose to write it."
HOOK_SECONDS = 3


def _accepted_candidates(text: str) -> dict[str, tuple[dict, dict]]:
    """{fact id: (its candidate line, its decision line)}, for each accepted candidate."""
    candidates: dict[str, dict] = {}
    accepted: dict[str, tuple[dict, dict]] = {}
    for line in text.splitlines():
        with contextlib.suppress(ValueError):
            record = json.loads(line)
            if not isinstance(record, dict):
                continue
            if record.get("type") == "candidate":
                candidates[str(record.get("id"))] = record
            elif record.get("type") == "decision" and record.get("status") == "accepted":
                candidate = candidates.get(str(record.get("id")))
                if candidate and record.get("fact_id"):
                    accepted[str(record["fact_id"])] = (candidate, record)
    return accepted


def _inside_a_hook(candidate: dict, decision: dict) -> bool:
    """True when the decision came as fast as only the hook's own gate run could make it."""
    try:
        gap = parse_time(str(decision.get("at"))) - parse_time(str(candidate.get("created_at")))
    except (ValueError, TypeError):
        return False
    return 0 <= gap.total_seconds() <= HOOK_SECONDS


def _gate_wrote(state: dict, candidate: dict) -> bool:
    """True when the fact is what the gate wrote for this candidate, and nobody touched it since."""
    text = str(candidate.get("text", "")).strip()
    source = str(candidate.get("source", ""))
    return (
        state.get("status") == "active"
        and state.get("scope") == "long"
        and state.get("basis") == GATE_BASIS
        and state.get("kind") in GATE_KINDS
        and state.get("kind") == candidate.get("kind")
        and state.get("text") == text
        and len(text) in GATE_TEXT_LENGTH
        and state.get("source") == source
        and source.startswith(GATE_SOURCES)
        and state.get("area") == (candidate.get("area") or "general")
        and not any(state.get(name) for name in ("pinned", "summary", "tags", "history"))
    )


def clean(memory: Memory) -> list[str]:
    """End the facts that 0.3.1's gate accepted. Remove its files. Return the ended ids."""
    path = memory.dir / CANDIDATE_FILE
    ended: list[Retirement] = []
    if path.exists():
        # A damaged file holds no fact, so each line that can be read is enough.
        text = path.read_bytes().decode("utf-8", errors="replace")
        for fact_id, (candidate, decision) in sorted(_accepted_candidates(text).items()):
            state = memory.states.get(fact_id)
            if state and _gate_wrote(state, candidate) and _inside_a_hook(candidate, decision):
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
