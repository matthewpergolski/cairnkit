"""Session state for hooks: what changed since the session started.

The state lives in `<memory>/.sessions/<id>.json`. It is local, small and safe
to delete.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from cairnkit.clock import now, parse_time, stamp
from cairnkit.memory import Memory
from cairnkit.paths import run_git

KEEP_DAYS = 7


def _path(memory: Memory, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", session_id or "default")[:80] or "default"
    return memory.dir / ".sessions" / f"{safe}.json"


def fingerprint(root: Path) -> str:
    """A hash of HEAD, the status and the diff. It changes when the work changes."""
    parts = [
        run_git(root, "rev-parse", "HEAD", timeout=2.0) or "",
        run_git(root, "status", "--porcelain", "--untracked-files=all", timeout=2.0) or "",
        run_git(root, "diff", "HEAD", timeout=2.0) or "",
    ]
    return hashlib.sha1("\0".join(parts).encode()).hexdigest()


def load_state(memory: Memory, session_id: str) -> dict | None:
    try:
        return json.loads(_path(memory, session_id).read_text())
    except (OSError, ValueError):
        return None


def save_state(memory: Memory, session_id: str, state: dict) -> None:
    path = _path(memory, session_id)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(state))
    _prune(path.parent)


def _prune(folder: Path) -> None:
    limit = time.time() - KEEP_DAYS * 86400
    for old in folder.glob("*.json"):
        try:
            if old.stat().st_mtime < limit:
                old.unlink()
        except OSError:
            pass


def start_session(memory: Memory, session_id: str) -> None:
    save_state(
        memory,
        session_id,
        {"started_at": stamp(now()), "start": fingerprint(memory.project.root)},
    )


def wrote_since(memory: Memory, moment: str) -> bool:
    since = parse_time(moment)
    for rec in memory.records:
        when = rec.get("learned_at") if rec.get("type") == "fact" else rec.get("at")
        try:
            if when and parse_time(when) >= since:
                return True
        except ValueError:
            continue
    return False


def needs_reminder(memory: Memory, session_id: str) -> bool:
    """True once per new state of the work, when no fact was written for it."""
    state = load_state(memory, session_id)
    current = fingerprint(memory.project.root)
    if state is None:
        start_session(memory, session_id)
        return False
    if current in (state.get("start"), state.get("reminded")):
        return False
    if wrote_since(memory, state.get("reminded_at") or state["started_at"]):
        return False
    state["reminded"] = current
    state["reminded_at"] = stamp(now())
    save_state(memory, session_id, state)
    return True
