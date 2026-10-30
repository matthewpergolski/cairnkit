"""Quality gate for pending auto-candidates, and the auto-tidy cadence.

Defaults (documented here on purpose):

- Run the gate after 5 new pending candidates (`PENDING_TRIGGER`), or after
  30 minutes since the last gate run (`INTERVAL_SECONDS`).
- Auto-accept only when every check passes: kind is lesson/decision/trap,
  text length in [MIN_LEN, MAX_LEN], source starts with commit: or file:,
  no secret hit, and not a near-dup of an active fact.
- Near-dup among pending: dismiss the newer one.
- Near-dup of an active fact: dismiss the pending candidate.
- Undecidable pending stay pending and surface once on session-start.

Clear mechanical fact retires stay in `autotidy`. This module only decides
pending candidates.
"""

from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace

from cairnkit.clock import now, parse_time, stamp
from cairnkit.memory import Memory
from cairnkit.pending import decide, pending
from cairnkit.propose import PREFERRED, near_active
from cairnkit.secretscan import find_secrets
from cairnkit.similar import analyze, similarity
from cairnkit.store import locked
from cairnkit.writing import Refused, add_fact

STATE_NAME = ".autogate-state.json"
LOCK_NAME = ".autogate.lock"
PENDING_TRIGGER = 5
INTERVAL_SECONDS = 30 * 60
MIN_LEN = 40
MAX_LEN = 500
GATE_KINDS = PREFERRED  # lesson / decision / trap


def _state(memory: Memory) -> dict:
    try:
        data = json.loads((memory.dir / STATE_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(memory: Memory, data: dict) -> None:
    (memory.dir / STATE_NAME).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def should_run(memory: Memory, *, new_pending: int = 0) -> bool:
    """True when cadence says to run the gate (N new pending or interval elapsed)."""
    data = _state(memory)
    if new_pending >= PENDING_TRIGGER:
        return True
    since = int(data.get("pending_since_gate", 0)) + new_pending
    if since >= PENDING_TRIGGER:
        return True
    last = data.get("last_gate_at")
    if not last:
        return bool(pending(memory))
    try:
        age = (now() - parse_time(last)).total_seconds()
    except ValueError:
        return True
    return age >= INTERVAL_SECONDS and bool(pending(memory))


def note_pending(memory: Memory, added: int) -> None:
    """Count newly drafted pending candidates toward the cadence."""
    if added <= 0:
        return
    with locked(memory.dir / LOCK_NAME):
        data = _state(memory)
        data["pending_since_gate"] = int(data.get("pending_since_gate", 0)) + added
        _save(memory, data)


def _mark_ran_unlocked(memory: Memory) -> None:
    data = _state(memory)
    data["last_gate_at"] = stamp(now())
    data["pending_since_gate"] = 0
    _save(memory, data)


def mark_ran(memory: Memory) -> None:
    with locked(memory.dir / LOCK_NAME):
        _mark_ran_unlocked(memory)


def grounded(source: str) -> bool:
    return source.startswith(("commit:", "file:")) and len(source.split(":", 1)[-1].strip()) >= 3


def passes_gate(cand) -> bool:
    text = cand.text.strip()
    if cand.kind not in GATE_KINDS:
        return False
    if not (MIN_LEN <= len(text) <= MAX_LEN):
        return False
    if not grounded(str(cand.source)):
        return False
    return not (find_secrets(text) or find_secrets(str(cand.source)))


def _near_pending_pairs(items: list) -> list[tuple[str, str]]:
    """Pairs (keep_id, dismiss_id) among pending near-duplicates."""
    words = {c.id: analyze(c.text) for c in items}
    pairs = []
    seen: set[tuple[str, str]] = set()
    ordered = sorted(items, key=lambda c: (c.created_at, c.id))
    for i, older in enumerate(ordered):
        for newer in ordered[i + 1 :]:
            if older.kind != newer.kind:
                continue
            score = similarity(words[older.id], words[newer.id])
            if score is None:
                continue
            key = (older.id, newer.id)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((older.id, newer.id))
    return pairs


def _accept(memory: Memory, cand) -> str | None:
    args = SimpleNamespace(
        text=cand.text,
        summary=None,
        kind=cand.kind,
        area=cand.area or "general",
        basis=getattr(cand, "basis", None) or "guess",
        source=cand.source,
        tag=None,
        happened_at=None,
        link=None,
        pinned=False,
        enforced_by=None,
        supersedes=None,
        reason=None,
        short=False,
        expires=None,
        until_merged=None,
    )
    try:
        fact_id = add_fact(memory, args)
    except Refused:
        return None
    if not fact_id:
        return None
    decide(memory, cand.id, "accepted", fact_id=fact_id)
    return fact_id


def run_gate(memory: Memory) -> list[str]:
    """Dismiss near-dups, auto-accept quality-gate passers. Return accepted fact ids."""
    accepted: list[str] = []
    with locked(memory.dir / LOCK_NAME):
        memory.reload()
        items = pending(memory)
        if not items:
            _mark_ran_unlocked(memory)
            return accepted
        for keep, drop in _near_pending_pairs(items):
            try:
                decide(
                    memory,
                    drop,
                    "dismissed",
                    reason=f"Near duplicate of pending {keep}.",
                )
            except (KeyError, ValueError):
                continue
        memory.reload()
        items = pending(memory)
        for cand in items:
            if near_active(memory, cand.text, cand.kind):
                with contextlib.suppress(KeyError, ValueError):
                    decide(
                        memory,
                        cand.id,
                        "dismissed",
                        reason="Near duplicate of an active fact.",
                    )
                continue
            if not passes_gate(cand):
                continue
            fact_id = _accept(memory, cand)
            if fact_id:
                accepted.append(fact_id)
        _mark_ran_unlocked(memory)
    memory.reload()
    return accepted


def hygiene_pending_line(memory: Memory) -> str | None:
    """One session-start line for undecidable pending. Empty when already shown."""
    items = pending(memory)
    if not items:
        return None
    with locked(memory.dir / LOCK_NAME):
        data = _state(memory)
        shown = data.get("hygiene_shown_ids") or []
        ids = [c.id for c in items]
        if set(ids) <= set(shown):
            return None
        data["hygiene_shown_ids"] = sorted(set(shown) | set(ids))
        _save(memory, data)
    return (
        f"{len(items)} pending auto-candidate(s). Review with `memory candidates list`, "
        "then `memory candidates accept ID` or `reject ID`."
    )


def maybe_run(memory: Memory, *, new_pending: int = 0) -> list[str]:
    """Run the gate when cadence says so. Always safe to call."""
    note_pending(memory, new_pending)
    if not should_run(memory, new_pending=0):
        return []
    return run_gate(memory)
