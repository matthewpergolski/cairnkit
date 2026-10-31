"""Untracked files that load the rules block for harnesses that skip CLAUDE.local.md.

Each path is kept out of git with `.git/info/exclude`. Codex gets the rules from its
SessionStart hook, so the tool writes nothing to its tracked `AGENTS.md`. OpenCode has no
native project-local rules file that loads without a tracked config or a plugin. That gap
is documented, not papered over with a tracked write.
"""

from __future__ import annotations

from dataclasses import dataclass

from cairnkit.instructions import block


@dataclass(frozen=True)
class Target:
    """One local file a harness reads, relative to the checkout root."""

    rel: str
    harness: str
    prefix: str = ""


# Cursor loads .cursor/rules/*.mdc with alwaysApply frontmatter.
# Pi appends .pi/APPEND_SYSTEM.md after trust.
# Claude Code and Grok Build read CLAUDE.local.md (the primary local file).
# Codex: the SessionStart hook.
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
