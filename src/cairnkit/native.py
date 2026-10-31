"""An agent tool's own memory reaches only that tool. Name it once, so the agent can copy facts.

The tool copies nothing itself: a fact must come from an agent's judgment, and `memory add` looks
for secrets. Only Claude Code has a per-project store that a file path can find. The other tools
keep their notes in tracked files or in places that are not per project.
"""

from __future__ import annotations

import json
from pathlib import Path

from cairnkit.memory import Memory

STATE_NAME = ".native-memory.json"


def _claude_store(root: Path) -> Path:
    slug = str(root.resolve()).replace("/", "-").replace(".", "-").replace("_", "-")
    return Path.home() / ".claude" / "projects" / slug / "memory"


def session_line(memory: Memory) -> str | None:
    """One line when the native store has entries that this memory has not named yet."""
    store = _claude_store(memory.project.main_root)
    entries = sorted(p.name for p in store.glob("*.md") if p.name != "MEMORY.md")
    if not entries:
        return None
    path = memory.dir / STATE_NAME
    try:
        known = set(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        known = set()
    new = [name for name in entries if name not in known]
    if not new:
        return None
    path.write_text(json.dumps(entries), encoding="utf-8")
    return (
        f"Claude Code's own memory has {len(new)} new note(s) in {store}. Other agents cannot "
        'see them. Read them, and copy what matters with `memory add "TEXT" --basis told|seen '
        "--source file:NAME`."
    )
