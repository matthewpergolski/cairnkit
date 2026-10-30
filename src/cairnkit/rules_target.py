"""Where the rules block goes: untracked CLAUDE.local.md only.

Hand-written project instructions stay in tracked CLAUDE.md / AGENTS.md.
cairnkit never writes its marked block into those files. Existing installs
move the block out into CLAUDE.local.md. Companion untracked files cover
harnesses that do not read CLAUDE.local.md (see harness_local).

Claude Code reads AGENTS.md only when it finds no CLAUDE.md,
.claude/CLAUDE.md or CLAUDE.local.md. So when only AGENTS.md is present,
local mode starts CLAUDE.local.md with @AGENTS.md, outside the markers.
"""

from __future__ import annotations

import errno
from pathlib import Path

from cairnkit import markers
from cairnkit.harness_local import TARGETS as HARNESS_TARGETS
from cairnkit.instructions import PAIRS

LOCAL = "CLAUDE.local.md"
OLD_LOCAL = "AGENTS.local.md"
HOME = "CLAUDE.md"
SHARED = (HOME, "AGENTS.md")  # hand-written homes; never receive the cairnkit block
LOOKED_AT = (*SHARED, LOCAL, *(t.rel for t in HARNESS_TARGETS))

IMPORT = "@AGENTS.md"


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
    names = (*LOOKED_AT, *([extra] if extra else []))
    return [n for n in dict.fromkeys(names) if is_loop(root / n)]


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


def local_file(_root: Path | None = None) -> str:
    """The untracked file that holds the cairnkit rules block and tidy promotions."""
    return LOCAL
