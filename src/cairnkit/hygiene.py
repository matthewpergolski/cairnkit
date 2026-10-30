"""Read-only staleness hints for `memory load`. Never writes proposals."""

from __future__ import annotations

from pathlib import Path

from cairnkit.clock import now, parse_time
from cairnkit.memory import Memory
from cairnkit.paths import run_git
from cairnkit.state import effective_status

DEFAULT_DAYS = 90


def _age_days(state: dict, moment) -> float:
    try:
        return (moment - parse_time(state["learned_at"])).total_seconds() / 86400
    except (KeyError, ValueError, TypeError):
        return 0.0


def _file_missing(root: Path, source: str) -> bool:
    if not source.startswith("file:"):
        return False
    path = source[5:]
    if not path or path.startswith(("/", "~")):
        return False
    return not (root / path).exists()


def _commit_missing(root: Path, source: str) -> bool:
    if not source.startswith("commit:"):
        return False
    value = source[7:].strip()
    if not value or len(value) < 7:
        return False
    probed = run_git(root, "rev-parse", "--verify", f"{value}^{{commit}}", timeout=1.0)
    return probed is None


def hygiene_line(memory: Memory, days: int = DEFAULT_DAYS) -> str | None:
    """One line for load when facts look stale or point at missing sources."""
    moment = now()
    root = memory.project.root
    linked = {link["id"] for s in memory.states.values() for link in s.get("links", [])}
    linked |= {s["id"] for s in memory.states.values() if s.get("links")}
    stale = 0
    missing_file = 0
    missing_commit = 0
    for state in memory.states.values():
        status, _ = effective_status(state, moment, None)
        if status != "active":
            continue
        if (
            state.get("scope", "long") == "long"
            and not state.get("pinned")
            and state["id"] not in linked
            and _age_days(state, moment) > days
        ):
            stale += 1
        source = str(state.get("source", ""))
        if _file_missing(root, source):
            missing_file += 1
        elif _commit_missing(root, source):
            missing_commit += 1
    parts = []
    if stale:
        parts.append(f"{stale} older than {days} days with no links")
    if missing_file:
        parts.append(f"{missing_file} file source(s) missing")
    if missing_commit:
        parts.append(f"{missing_commit} commit source(s) missing")
    if not parts:
        return None
    return f"Stale memory: {'; '.join(parts)}. Run `memory tidy` and review."
