"""An agent tool's own memory reaches only that tool. Name it once, so the agent can copy facts.

The tool copies nothing itself: a fact must come from an agent's judgment, and `memory add` looks
for secrets. Only Claude Code has a per-project store that a file path can find. The other tools
keep their notes in tracked files or in places that are not per project. The tool reads that store
and never writes to it, so it names a value that looks secret there and prints no value.
"""

from __future__ import annotations

import json
from pathlib import Path

from cairnkit.memory import Memory
from cairnkit.secretscan import real_secrets

STATE_NAME = ".native-memory.json"
MAX_BYTES = 256 * 1024


def _claude_store(root: Path) -> Path:
    slug = str(root.resolve()).replace("/", "-").replace(".", "-").replace("_", "-")
    return Path.home() / ".claude" / "projects" / slug / "memory"


def _secret_places(memory: Memory, store: Path, names: list[str]) -> list[str]:
    places = []
    for name in names:
        path = store / name
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, start=1):
            found = real_secrets(line, memory.env)
            if found:
                places.append(f"{name}:{number} ({', '.join(found)})")
    return places


def _secret_text(places: list[str]) -> str:
    return (
        f"These hold a value that looks secret: {', '.join(places)}. Do not copy that value. "
        "This tool does not edit that store. If the value is real, remove it there and change it."
    )


def secret_note(memory: Memory) -> str | None:
    """For `memory check`. No exit code depends on it: that store is not this tool's to clean."""
    store = _claude_store(memory.project.main_root)
    places = _secret_places(memory, store, sorted(p.name for p in store.glob("*.md")))
    return f"note: Claude Code's own memory. {_secret_text(places)}" if places else None


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
    line = (
        f"Claude Code's own memory has {len(new)} new note(s) in {store}. Other agents cannot "
        'see them. Read them, and copy what matters with `memory add "TEXT" --basis told|seen '
        "--source file:NAME`."
    )
    places = _secret_places(memory, store, new)
    return f"{line} {_secret_text(places)}" if places else line
