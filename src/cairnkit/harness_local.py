"""Untracked files that load the rules block for harnesses that skip CLAUDE.local.md.

Each path is kept out of git with `.git/info/exclude`. Codex reads tracked
`AGENTS.md` instead of an override file; init adds one pointer line there
(see `AGENTS_POINTER`). OpenCode has no native project-local rules file that
loads without a tracked config or a plugin; that gap is documented, not
papered over with a tracked write.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cairnkit.instructions import block

# One line in tracked AGENTS.md. No product name. Idempotent when already present.
AGENTS_POINTER = "Also read `CLAUDE.md`, and `CLAUDE.local.md` if it exists."
AGENTS_FILE = "AGENTS.md"
STALE_OVERRIDE = "AGENTS.override.md"


@dataclass(frozen=True)
class Target:
    """One local file a harness reads, relative to the checkout root."""

    rel: str
    harness: str
    prefix: str = ""


# Cursor loads .cursor/rules/*.mdc with alwaysApply frontmatter.
# Pi appends .pi/APPEND_SYSTEM.md after trust.
# Claude Code and Grok Build read CLAUDE.local.md (the primary local file).
# Codex: tracked AGENTS.md pointer only (no override copy).
TARGETS = (
    Target(
        ".cursor/rules/cairnkit.mdc",
        "Cursor",
        prefix="---\nalwaysApply: true\n---\n\n",
    ),
    Target(".pi/APPEND_SYSTEM.md", "Pi"),
)

# OpenCode: no reliable untracked project rules load without a tracked
# opencode.json `instructions` entry or an unreleased local-config / plugin path.
OPENCODE_GAP = (
    "OpenCode has no stable untracked project rules file. It loads committed "
    "AGENTS.md and optional `instructions` paths from opencode.json. Do not "
    "fall back to a tracked write; connect with hooks or a local config the "
    "user owns outside cairnkit."
)


def body_for(target: Target) -> str:
    """Full file text for a new harness local file."""
    return target.prefix + block()


def rels() -> tuple[str, ...]:
    return tuple(t.rel for t in TARGETS)


def ensure_agents_pointer(root: Path, dry_run: bool = False) -> tuple[str, bool]:
    """Ensure AGENTS.md holds the pointer line once. Create the file if missing.

    Return (action, removed_stale_override). Action is created, appended,
    unchanged, or would-*. Never writes cairnkit markers.
    """
    path = root / AGENTS_FILE
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        if AGENTS_POINTER in text:
            action = "unchanged"
        elif dry_run:
            action = "would-append"
        else:
            sep = "" if text.endswith("\n") else "\n"
            blank = "" if text.endswith("\n\n") or not text.strip() else "\n"
            path.write_text(text + sep + blank + AGENTS_POINTER + "\n")
            action = "appended"
    elif dry_run:
        action = "would-create"
    else:
        path.write_text(AGENTS_POINTER + "\n")
        action = "created"
    stale = root / STALE_OVERRIDE
    removed = False
    if stale.is_file():
        if dry_run:
            removed = True
        else:
            stale.unlink()
            removed = True
    return action, removed
