"""`memory init`: make the memory folder, link it into every checkout, ignore the link."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cairnkit.ignore import append_lines, exclude, is_tracked, missing_lines
from cairnkit.paths import LINK_NAME, PATH_FILE, Project, resolve_memory_dir
from cairnkit.presets import NONE, apply

IGNORE_LINES = [LINK_NAME, PATH_FILE]

README = """\
# Project memory

This folder is the private memory of one project. It is not part of the repo.
The project holds a link to it named `memory-bank`. Git ignores that link.

- `facts/` holds append-only fact files, one per writer. Use the `memory` tool to write them.
- `notes/` holds prose: `status.md` (where things stand now) and other notes.
- `branches/` holds working notes for one branch: `branches/<branch>.md`.
- `config.toml` holds settings for this memory.

Do not edit fact files by hand. Run `memory --help`.
"""

CONFIG = """\
# Settings for this project's memory.

# Days until a short-term fact expires, when it has no expires_at.
short_term_days = 14

# The untracked rules file. `memory tidy` proposes durable facts for it.
# Unset, it is CLAUDE.local.md. Must stay out of git.
# rules_file = "CLAUDE.local.md"

# What the session-start hook does with facts that are clearly redundant (exact
# repeats, ended short-term facts). The same step runs after a git push or
# merge. Those hooks are personal. A push does not count as a session start.
# "auto" (the default) only reports for the
# first 3 session starts and 7 days, then turns itself on, unless a retire was
# undone. "report", "on" and "off" force a mode. `memory tidy --auto` always retires.
# auto_tidy = "auto"

# Map path prefixes to areas. `memory load` ranks facts higher when the
# branch changes files under a prefix.
[areas]
# "src/db/" = "database"
# "docs/" = "docs"
"""

STATUS = "# Status\n\n<!-- Where things stand now. Rewrite this file; do not append. -->\n"


def _real_files(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*") if not p.is_dir())


def plan_link(
    checkout: Path, memdir: Path, moved: frozenset[Path] = frozenset()
) -> tuple[str, str | None]:
    """Return (action, problem). Action is one of: ok, create, relink, replace-empty.

    A link path in `moved` holds a real folder that `memory migrate` is about to
    move away, so it counts as free.
    """
    link = checkout / LINK_NAME
    if link in moved:
        return "create", None
    if link.is_symlink():
        if link.resolve() == memdir.resolve():
            return "ok", None
        return "relink", None
    if link.is_dir():
        files = _real_files(link)
        if files:
            shown = ", ".join(files[:10]) + (" ..." if len(files) > 10 else "")
            return "refuse", f"{link} is a real folder with files: {shown}"
        return "replace-empty", None
    if link.exists():
        return "refuse", f"{link} is a file, not a link"
    return "create", None


def _ignore_targets(project: Project, write_gitignore: bool) -> list[Path]:
    targets = []
    if write_gitignore:
        targets.append(project.root / ".gitignore")
    if project.common_dir is not None:
        targets.append(project.common_dir / "info" / "exclude")
    return targets


def _missing_ignore_lines(path: Path) -> list[str]:
    return missing_lines(path, IGNORE_LINES)


def _append_ignore(path: Path, lines: list[str]) -> None:
    append_lines(path, lines)


def _write_skeleton(memdir: Path) -> list[str]:
    made = []
    for sub in ("facts", "notes", "branches"):
        if not (memdir / sub).is_dir():
            (memdir / sub).mkdir(parents=True)
            made.append(f"{sub}/")
    for rel, text in (("README.md", README), ("config.toml", CONFIG), ("notes/status.md", STATUS)):
        if not (memdir / rel).exists():
            (memdir / rel).write_text(text)
            made.append(rel)
    return made


def is_linked(checkout: Path, memdir: Path) -> bool:
    """True when checkout's memory-bank symlink resolves to memdir."""
    link = checkout / LINK_NAME
    return link.is_symlink() and link.exists() and link.resolve() == memdir.resolve()


def can_link(project: Project, checkout: Path, memdir: Path) -> bool:
    """True when ensure_linked would create a link in this checkout."""
    link = checkout / LINK_NAME
    return (
        (memdir / "facts").is_dir()
        and not os.path.lexists(link)
        and not is_tracked(project, LINK_NAME, checkout)
    )


def ensure_linked(
    project: Project,
    checkout: Path,
    flag: str | None = None,
    memdir: Path | None = None,
) -> str | None:
    """Link checkout to the project's memory when the link is plainly missing.

    Memory is resolved from the main checkout, so a worktree needs no
    .memory-path of its own. Acts only on a missing path that git does not
    track in this checkout, and only when the memory folder exists. Returns a
    notice, or None.
    """
    if memdir is None:
        memdir, _ = resolve_memory_dir(project, flag)
    link = checkout / LINK_NAME
    if not can_link(project, checkout, memdir):
        return None
    target = os.path.relpath(memdir, checkout)
    try:
        exclude(project, IGNORE_LINES)  # first: a link git does not ignore is worse than none
    except OSError:
        return None
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        return None
    return f"memory: linked {link} -> {target}"


def ensure_all_linked(project: Project, flag: str | None = None) -> list[str]:
    """Ensure every checkout is linked. Return the notice lines that were printed."""
    memdir, _ = resolve_memory_dir(project, flag)
    return [
        line
        for checkout in project.checkouts
        if (line := ensure_linked(project, checkout, flag, memdir))
    ]


def link_here(project: Project, flag: str | None = None) -> str | None:
    """Link this checkout when its memory link is plainly missing. Return a line, or None."""
    return ensure_linked(project, project.root, flag)


def run_init(
    project: Project,
    path_flag: str | None,
    dry_run: bool = False,
    write_gitignore: bool = False,
    presets: list[str] | None = None,
    moved: frozenset[Path] = frozenset(),
) -> int:
    """Add the rules of the presets. With presets None, add no rule facts.

    The rules about memory itself ship inside the tool (`memory instructions`).
    """
    cwd = Path.cwd().absolute()
    if not project.is_git and project.root != cwd:
        memdir, _ = resolve_memory_dir(project, None)
        print(
            f"error: {cwd} is inside the project at {project.root}, which already has a memory "
            f"({memdir}).\nNothing changed. The memory commands work from this subfolder. "
            "To change the project, run `memory init` in its root folder.",
            file=sys.stderr,
        )
        return 1
    memdir, source = resolve_memory_dir(project, path_flag)
    say = print
    if dry_run:
        say("Dry run: nothing will change.")
    say(f"Memory folder: {memdir} (from {source})")

    plans = [(c, *plan_link(c, memdir, moved)) for c in project.checkouts]
    problems = [p for _, _, p in plans if p]
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print(
            "Nothing changed. Move these files into the memory folder first (migrate),\n"
            "then remove the real folder and run `memory init` again.",
            file=sys.stderr,
        )
        return 1

    steps: list[str] = []
    if not memdir.is_dir():
        steps.append(f"create {memdir}")
    if path_flag:
        rel = os.path.relpath(memdir, project.main_root)
        current = project.main_root / PATH_FILE
        if not current.is_file() or current.read_text().splitlines()[:1] != [rel]:
            steps.append(f"write {current}: {rel}")
            if not dry_run:
                current.write_text(rel + "\n")
    if not dry_run:
        memdir.mkdir(parents=True, exist_ok=True)
        steps += [f"add {memdir / m}" for m in _write_skeleton(memdir)]
    wanted = presets or []
    rule_lines: list[str] = []
    if wanted and wanted != [NONE]:
        count, lines = apply(project, memdir, wanted, dry_run)
        if count:
            steps.append(f"add {count} rule fact(s) to {memdir / 'facts'}")
            rule_lines = lines

    for checkout, action, _ in plans:
        link = checkout / LINK_NAME
        target = os.path.relpath(memdir, checkout)
        if action == "ok":
            continue
        steps.append(f"{action} link {link} -> {target}")
        if dry_run:
            continue
        if action == "relink":
            link.unlink()
        elif action == "replace-empty":
            link.rmdir()
        link.symlink_to(target, target_is_directory=True)

    for ignore_file in _ignore_targets(project, write_gitignore):
        missing = _missing_ignore_lines(ignore_file)
        if missing:
            steps.append(f"add {', '.join(missing)} to {ignore_file}")
            if not dry_run:
                _append_ignore(ignore_file, missing)

    for step in steps:
        say(("would " if dry_run else "") + step)
    for line in rule_lines:
        say(line)
    if not steps:
        say("Already set up. Nothing to do.")
    if not dry_run:
        say("Run `memory hooks install` to connect your agent and git.")
    return 0
