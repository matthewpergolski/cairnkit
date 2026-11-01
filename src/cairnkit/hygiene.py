"""Read-only prompts for `memory load`: a source that is gone, a status behind the code.

Age plays no part, and neither prompt ends a fact.
"""

from __future__ import annotations

import re
from pathlib import Path

from cairnkit.clock import now
from cairnkit.memory import Memory
from cairnkit.paths import run_git
from cairnkit.state import effective_status

SHOW_IDS = 5
COMMIT_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
MAX_NAMED = 50


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


def hygiene_line(memory: Memory) -> str | None:
    """One line that names the facts whose source file or commit no longer exists."""
    moment = now()
    root = memory.project.root
    gone = []
    for state in memory.states.values():
        status, _ = effective_status(state, moment, None)
        if status != "active":
            continue
        source = str(state.get("source", ""))
        if _file_missing(root, source) or _commit_missing(root, source):
            gone.append(state["id"])
    if not gone:
        return None
    names = ", ".join(sorted(gone)[:SHOW_IDS]) + (" and more" if len(gone) > SHOW_IDS else "")
    return (
        f"Source gone: {len(gone)} fact(s) name a file or commit that no longer exists: {names}. "
        "If you touch that work, check each fact. End one with `memory change ID --status "
        'expired --reason "..."`.'
    )


def commits_past_status(root: Path, path: Path) -> str:
    """Words for the status heading: how far HEAD is past the newest commit that the note names.

    A note cites old commits as history, so only the newest one says how old the note is.
    `--not` over all of them counts from the newest. A hex word that is no commit is ignored.
    """
    try:
        named = sorted(set(COMMIT_RE.findall(path.read_text(encoding="utf-8"))))[:MAX_NAMED]
    except (OSError, UnicodeDecodeError):
        return ""
    if not named:
        return ""
    known = run_git(
        root, "log", "--no-walk", "--ignore-missing", "--format=%H", *named, timeout=1.0
    )
    if not known:
        return ""
    count = run_git(root, "rev-list", "--count", "HEAD", "--not", *known.split(), timeout=1.0)
    if not count or count == "0":
        return ""
    return f"; HEAD is {count} commit(s) past the newest commit it names"
