"""Find the project, its checkouts, and its memory folder."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

LINK_NAME = "memory-bank"
PATH_FILE = ".memory-path"
ENV_DIR = "MEMORY_DIR"


@dataclass
class Project:
    """One project: the checkout we are in, the main checkout, and all worktrees."""

    root: Path
    main_root: Path
    checkouts: list[Path] = field(default_factory=list)
    common_dir: Path | None = None

    @property
    def is_git(self) -> bool:
        return self.common_dir is not None


def run_git(cwd: Path, *args: str, timeout: float = 3.0) -> str | None:
    """Run git. Return its output, or None when git fails or is missing."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def find_project(cwd: Path | None = None) -> Project:
    cwd = Path(cwd or Path.cwd()).absolute()
    top = run_git(cwd, "rev-parse", "--show-toplevel")
    if top is None:
        root = plain_root(cwd)
        return Project(root=root, main_root=root, checkouts=[root])
    root = Path(top)
    common = Path(run_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir") or "")
    main_root = common.parent if common.name == ".git" else root
    checkouts = _list_worktrees(root) or [root]
    if main_root not in checkouts:
        checkouts.insert(0, main_root)
    return Project(root=root, main_root=main_root, checkouts=checkouts, common_dir=common)


def plain_root(cwd: Path) -> Path:
    """Outside git: the nearest folder, from cwd up, with a memory link or .memory-path.

    The walk does not check the home folder or the file system root, so one
    stray link there cannot catch every folder. With no match, cwd is the root.
    """
    stops = {Path.home().absolute(), Path(cwd.anchor)}
    folder = cwd
    while folder not in stops:
        if (folder / LINK_NAME).is_symlink() or (folder / PATH_FILE).is_file():
            return folder
        if folder.parent == folder:
            break
        folder = folder.parent
    return cwd


def _list_worktrees(root: Path) -> list[Path]:
    out = run_git(root, "worktree", "list", "--porcelain")
    if not out:
        return []
    paths = []
    bare = False
    for line in out.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.removeprefix("worktree ")))
            bare = False
        elif line == "bare":
            bare = True
            paths.pop()
        elif line == "prunable" or line.startswith("prunable "):
            if paths and not bare:
                paths.pop()
    return [p for p in paths if p.is_dir()]


def resolve_memory_dir(project: Project, flag: str | None = None) -> tuple[Path, str]:
    """Return the memory folder and where the setting came from.

    Order: flag, MEMORY_DIR, first line of .memory-path in the main checkout,
    then the default sibling folder `<main checkout>.memory`.
    """
    if flag:
        return Path(flag).expanduser().absolute(), "flag"
    env = os.environ.get(ENV_DIR)
    if env:
        return Path(env).expanduser().absolute(), ENV_DIR
    path_file = project.main_root / PATH_FILE
    if path_file.is_file():
        lines = path_file.read_text().splitlines()
        first = lines[0].strip() if lines else ""
        if first:
            target = Path(first).expanduser()
            if not target.is_absolute():
                target = project.main_root / target
            return Path(os.path.normpath(target)), PATH_FILE
    default = project.main_root.parent / f"{project.main_root.name}.memory"
    return default, "default"


def current_branch(root: Path) -> str | None:
    name = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    return name or None


def writer_name(root: Path) -> str:
    """The writer is MEMORY_WRITER, else the branch name, else `main`."""
    name = os.environ.get("MEMORY_WRITER") or current_branch(root) or "main"
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in name).strip(".-")
    return safe or "main"


def default_branch(root: Path) -> str | None:
    """The branch that work merges into: origin's HEAD, else main, else master."""
    remote = run_git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote:
        return remote.split("/", 1)[-1]
    for name in ("main", "master"):
        if run_git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}") is not None:
            return name
    return None


def merged_checker(root: Path):
    """Return a cached function: is this branch merged into the default branch?

    A branch that no longer exists counts as merged (its work is done).
    """
    base = default_branch(root)
    cache: dict[str, bool] = {}

    def is_merged(branch: str) -> bool:
        if branch in cache:
            return cache[branch]
        result = False
        if base and branch != base:
            tip = run_git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
            if tip is None:
                result = True
            else:
                base_tip = run_git(root, "rev-parse", f"refs/heads/{base}")
                ancestor = run_git(root, "merge-base", "--is-ancestor", tip, base) is not None
                result = ancestor and tip != base_tip
        cache[branch] = result
        return result

    return is_merged
