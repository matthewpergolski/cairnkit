"""Which file takes the rules block.

Local mode writes `CLAUDE.local.md`. Shared mode follows the files the repo
already has: `CLAUDE.md` first, then `AGENTS.md`. A repo with neither gets
`CLAUDE.md`, and an `AGENTS.md` that only points to it.

Shared mode edits an existing `AGENTS.md` in two cases only: it is the repo's
only rules file (the block is appended), or it already holds a block (the block
is refreshed). When `CLAUDE.md` exists and `AGENTS.md` holds no block,
`AGENTS.md` is not touched. Text outside the markers never changes.

Claude Code reads `AGENTS.md` only when it finds no `CLAUDE.md`,
`.claude/CLAUDE.md` or `CLAUDE.local.md`. So when only `AGENTS.md` is shared,
local mode starts `CLAUDE.local.md` with `@AGENTS.md`, outside the markers.
"""

from __future__ import annotations

import errno
from dataclasses import dataclass, field
from pathlib import Path

from cairnkit import markers
from cairnkit.instructions import PAIRS

LOCAL = "CLAUDE.local.md"
OLD_LOCAL = "AGENTS.local.md"
HOME = "CLAUDE.md"
SHARED = (HOME, "AGENTS.md")
LOOKED_AT = (*SHARED, LOCAL)

IMPORT = "@AGENTS.md"

POINTER = f"""\
# Agent instructions

The project rules live in {HOME}. Read it first.
Also read {LOCAL} if it exists.
"""


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def is_loop(path: Path) -> bool:
    """True when path is, or sits behind, a symlink loop."""
    try:
        path.stat()
    except OSError as exc:
        return exc.errno == errno.ELOOP
    return False


def loops(root: Path, extra: str | None = None) -> list[str]:
    """The rules files (and the chosen --instructions-file) that are symlink loops."""
    return [
        n for n in dict.fromkeys((*LOOKED_AT, *([extra] if extra else []))) if is_loop(root / n)
    ]


def link_target(root: Path, rel: str) -> str | None:
    """Where rel really is, as a path relative to root, or None when it is outside root."""
    try:
        return (root / rel).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def holds_block(path: Path) -> bool:
    """True when the file holds a rules block marker, new or old (even a broken one)."""
    return markers.find(_text(path), PAIRS)[0] != "missing"


def same_file(root: Path) -> bool:
    """True when CLAUDE.md and AGENTS.md are one file (one is a link to the other)."""
    one, two = (root / n for n in SHARED)
    return one.is_file() and two.is_file() and one.resolve() == two.resolve()


def needs_import(root: Path, rel: str) -> bool:
    """True when the local file must start with `@AGENTS.md`.

    Claude Code reads AGENTS.md only when it finds no CLAUDE.md, .claude/CLAUDE.md or
    CLAUDE.local.md. A CLAUDE.local.md without the import would hide a shared AGENTS.md.
    """
    agents, local = root / SHARED[1], root / rel
    if rel != LOCAL or not agents.is_file():
        return False
    if (root / HOME).is_file() or (root / ".claude" / HOME).is_file():
        return False
    if agents.resolve() == local.resolve():
        return False
    return IMPORT not in (line.strip() for line in _text(local).splitlines())


def add_import(path: Path) -> None:
    """Put the import and a blank line at the top, before any text that is already there."""
    path.write_text(f"{IMPORT}\n\n" + path.read_text(encoding="utf-8"), encoding="utf-8")


def present(root: Path) -> list[str]:
    """The rules files this checkout has, in the order of LOOKED_AT."""
    return [name for name in LOOKED_AT if (root / name).is_file()]


def shared_file(root: Path) -> str:
    """The shared rules file: CLAUDE.md if it exists, else AGENTS.md, else CLAUDE.md."""
    return next((n for n in SHARED if (root / n).is_file()), HOME)


@dataclass
class Choice:
    rel: str
    reason: str
    pointer: bool = False
    notes: list[str] = field(default_factory=list)


def _hint(root: Path) -> str:
    """For a repo with both files: how Claude Code and AGENTS.md-only tools find AGENTS.md."""
    imports = IMPORT in (line.strip() for line in _text(root / HOME).splitlines())
    load = (
        ""
        if imports
        else f"Claude Code reads {SHARED[1]} only when there is no {HOME}, so add `{IMPORT}` "
        f"at the top of {HOME} if those instructions should load there. "
    )
    return (
        f"hint: {SHARED[1]} does not mention {HOME}. It was left as it is. {load}"
        f"Tools that only read {SHARED[1]} will not see the rules block unless "
        f"{SHARED[1]} points to {HOME}."
    )


def choose_shared(root: Path) -> Choice:
    """Pick the file for the shared block. A file that already holds a block wins."""
    same = (root / SHARED[0]).resolve() == (root / SHARED[1]).resolve()  # one is a symlink
    names = SHARED[:1] if same else SHARED
    holders = [n for n in names if holds_block(root / n)]
    notes = []
    if len(holders) == 2:
        notes.append(
            f"note: both {SHARED[0]} and {SHARED[1]} hold a rules block. Remove one by hand."
        )
    if holders:
        return Choice(
            holders[0],
            f"{holders[0]} already holds the block, so it is refreshed there.",
            notes=notes,
        )
    has = [n for n in names if (root / n).is_file()]
    if not has:
        return Choice(
            HOME, f"Neither {SHARED[0]} nor {SHARED[1]} exists, so {HOME} is created.", pointer=True
        )
    rel = has[0]
    if same and has:
        return Choice(rel, f"{HOME} and {SHARED[1]} are the same file, so the block goes there.")
    if len(has) == 2:
        if HOME not in _text(root / SHARED[1]):
            notes.append(_hint(root))
        return Choice(rel, f"Both exist, so the block goes to {HOME}.", notes=notes)
    return Choice(rel, f"Only {rel} exists, so the block goes there.", notes=notes)
