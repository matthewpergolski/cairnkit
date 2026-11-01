"""`memory init`: make the memory folder, link it into every checkout, ignore the link."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from cairnkit.ignore import exclude, is_tracked, keep_out_of_git
from cairnkit.paths import (
    COPY,
    ENV_DIR,
    GIT_FOLDER_REFUSAL,
    LINK_NAME,
    OURS,
    PATH_FILE,
    Identity,
    Project,
    default_memory_dir,
    earlier_note,
    holds_memory,
    inside_git_folder,
    linked_memory,
    lost_memory,
    lost_note,
    owner_line,
    owner_state,
    project_key,
    read_identity,
    record_file,
    resolve_memory_dir,
    root_commits,
    write_identity,
)
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


# What the session-start hook does with facts that are clearly redundant (exact
# and near repeats, ended short-term facts, short-term facts whose source file
# is gone). The same step runs after a git push or
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
    """True when ensure_linked would create or repair a link in this checkout."""
    link = checkout / LINK_NAME
    dangling = link.is_symlink() and not link.exists()
    return (
        holds_memory(memdir)
        and (dangling or not os.path.lexists(link))
        and not is_tracked(project, LINK_NAME, checkout)
    )


def remember(project: Project, memdir: Path, source: str, chosen: bool = False) -> None:
    """Note where the memory is and who owns it, so a later move can be traced. Never raises.

    The memory folder gets an id and an owner. The repo records the id, the absolute path and
    its own git folder there, because a relative link says nothing once the repo has moved, and
    because a copied repo brings the record of the first repo along. That record stays until
    `memory init` runs in the copy (`chosen`). A new place also gets a look for work trees that
    hold it. The usual call reads two small files, and it runs no git.
    """
    if source in ("flag", ENV_DIR) or not holds_memory(memdir):
        return
    try:
        identity = read_identity(memdir)
        if identity is None:
            identity = Identity(uuid.uuid4().hex, root_commits(project), project_key(project))
            write_identity(memdir, identity)
        state, _ = owner_state(project, memdir)
        if state == COPY and not chosen:
            return
        if state == OURS and identity.owner != project_key(project):
            write_identity(memdir, identity._replace(owner=project_key(project)))
        path = record_file(project)
        if path is None:
            return
        text = f"{identity.id}\n{memdir.resolve()}\n{project_key(project)}\n"
        if not path.is_file() or path.read_text() != text:
            keep_out_of_git(memdir)
            path.write_text(text)
    except (OSError, UnicodeDecodeError):
        return


def ensure_linked(
    project: Project,
    checkout: Path,
    flag: str | None = None,
    memdir: Path | None = None,
) -> str | None:
    """Link checkout to the project's memory when the link is missing or dangles.

    Memory is resolved from the main checkout, so a worktree needs no
    .memory-path of its own. Acts only on a path that git does not track in this
    checkout, and only when the memory folder exists. Returns a notice, or None.
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
    repaired = link.is_symlink()
    try:
        if repaired:
            link.unlink()
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        return None
    return f"memory: {'relinked' if repaired else 'linked'} {link} -> {target}"


def ensure_all_linked(project: Project, flag: str | None = None) -> list[str]:
    """Ensure every checkout is linked. Return the notice lines that were printed."""
    memdir, source = resolve_memory_dir(project, flag)
    remember(project, memdir, source)
    return [
        line
        for checkout in project.checkouts
        if (line := ensure_linked(project, checkout, flag, memdir))
    ]


def link_here(project: Project, flag: str | None = None) -> str | None:
    """Link this checkout when its memory link is missing or dangles. Return a line, or None."""
    memdir, source = resolve_memory_dir(project, flag)
    remember(project, memdir, source)
    return ensure_linked(project, project.root, flag, memdir)


def real_folder_warning(project: Project, memdir: Path) -> str | None:
    """Name a real file or folder where the link belongs. Git puts one there on an old branch."""
    link = project.root / LINK_NAME
    if link.is_symlink() or not os.path.lexists(link):
        return None
    what = "real folder" if link.is_dir() else "real file"
    cause = (
        "because this branch tracks it (a branch from before the memory moved out of git)"
        if is_tracked(project, LINK_NAME)
        else "not a link"
    )
    return (
        f"warning: {link} is a {what}, {cause}. It is not your memory, and what it says can "
        f"be old, such as a status. Trust this load. The memory is at {memdir}."
    )


def _empty_path_refusal(project: Project, memdir: Path) -> str | None:
    """A --path to an empty folder must not leave the memory that the link reaches."""
    linked = linked_memory(project)
    if linked is None or linked == memdir.resolve():
        return None
    return (
        f"{LINK_NAME} points to the memory at {linked}, and {memdir} holds no memory. "
        "To move the memory: move the folder, then run `memory init --path NEW_PLACE`."
    )


def _own_memory_note(project: Project, memdir: Path, source: str) -> tuple[Path, str, str | None]:
    """The memory that init must use, its source, and a note when it had to leave another's.

    A stated path stays, and a repo that was copied has stated nothing, even when the copy
    brought a path file along. A link that nobody stated counts as nothing stated too.
    """
    if not holds_memory(memdir) or source in ("flag", ENV_DIR):
        return memdir, source, None
    state, _ = owner_state(project, memdir)
    if state == OURS or (state != COPY and source == PATH_FILE):
        return memdir, source, None
    own = default_memory_dir(project)
    return (
        own,
        "default",
        f"{memdir} belongs to another project, so this project now has its own memory at {own}. "
        f"What was added here before this stays in {memdir}.",
    )


def run_init(
    project: Project,
    path_flag: str | None,
    dry_run: bool = False,
    presets: list[str] | None = None,
    moved: frozenset[Path] = frozenset(),
    verbose: bool = True,
) -> int:
    """Add the rules of the presets. With presets None, add no rule facts.

    The rules about memory itself ship inside the tool (`memory instructions`).
    """
    cwd = Path.cwd().absolute()
    if inside_git_folder(cwd):
        print(GIT_FOLDER_REFUSAL.format(cwd=cwd), file=sys.stderr)
        return 1
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
    memdir, source, left_note = _own_memory_note(project, memdir, source)
    earlier: list[Path] = []
    if not holds_memory(memdir) and not moved and not left_note:
        lost = None if source in ("flag", ENV_DIR) else lost_memory(project)
        refusal = _empty_path_refusal(project, memdir) if source in ("flag", ENV_DIR) else None
        if lost and lost.gone:
            refusal = lost_note(lost)
        if refusal:
            print(f"error: {refusal}\nNothing changed.", file=sys.stderr)
            return 1
        earlier = lost.found if lost else []
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
    if not dry_run:
        leaks = keep_out_of_git(memdir)
        if leaks:
            for leak in leaks:
                print(f"error: {leak}", file=sys.stderr)
            print("Nothing changed.", file=sys.stderr)
            return 1

    steps: list[str] = []
    if left_note and (project.home / PATH_FILE).is_file():
        steps.append(f"remove {project.home / PATH_FILE}, which the copy brought along")
        if not dry_run:
            (project.home / PATH_FILE).unlink()
    if not memdir.is_dir():
        steps.append(f"create {memdir}")
    if path_flag:
        rel = os.path.relpath(memdir, project.home)
        current = project.home / PATH_FILE
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

    steps += exclude(project, IGNORE_LINES, dry_run)

    if not dry_run:
        remember(project, *resolve_memory_dir(project), chosen=True)

    if verbose or dry_run:
        for step in steps:
            say(("would " if dry_run else "") + step)
    for line in rule_lines:
        say(line)
    if not dry_run:
        state = "ready" if steps else "already set up"
        say(f"Memory {state}: {memdir} (linked as {LINK_NAME}; nothing in git changes).")
    earlier_line = earlier_note(earlier) if earlier else None
    for note in (left_note, earlier_line, owner_line(project, memdir)):
        if note:
            say(note)
    return 0
