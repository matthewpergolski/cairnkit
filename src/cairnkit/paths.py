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
    """The branch of this checkout. During a rebase, the branch being rebased."""
    name = run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    return name or _rebased_branch(root)


def _rebased_branch(root: Path) -> str | None:
    for state in ("rebase-merge", "rebase-apply"):
        path = run_git(
            root, "rev-parse", "--path-format=absolute", "--git-path", f"{state}/head-name"
        )
        try:
            head = Path(path or "").read_text().strip()
        except OSError:
            continue
        return head.removeprefix("refs/heads/") if head.startswith("refs/heads/") else None
    return None


def writer_name(root: Path) -> str:
    """The writer is MEMORY_WRITER, else the branch name, else `main`."""
    name = os.environ.get("MEMORY_WRITER") or current_branch(root) or "main"
    safe = "".join(c if c.isalnum() or c in "._-" else "-" for c in name).strip(".-")
    return safe or "main"


def earlier_names(root: Path, branch: str | None) -> set[str]:
    """The names this branch had before `git branch -m`, from its reflog."""
    if not branch:
        return set()
    log = run_git(root, "reflog", "show", "--format=%gs", f"refs/heads/{branch}", timeout=1.0) or ""
    prefix = "Branch: renamed refs/heads/"
    return {
        line[len(prefix) :].split(" to ", 1)[0]
        for line in log.splitlines()
        if line.startswith(prefix)
    }


def default_branch(root: Path) -> str | None:
    """The branch that work merges into: origin's HEAD, else main, else master."""
    remote = run_git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote:
        return remote.split("/", 1)[-1]
    for name in ("main", "master"):
        if run_git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}") is not None:
            return name
    return None


OPEN, DONE, UNKNOWN = "open", "done", "unknown"


def branch_reader(root: Path):
    """Return a cached function: (branch, recorded tip) to OPEN, DONE or UNKNOWN.

    A false end is worse than a stale note, so each read needs evidence.

    Open: a branch checked out in a worktree, a remote copy with no local branch,
    and a branch whose reflog shows no commit of its own in the default branch.
    Done: a branch that is not checked out and whose own commits landed by a merge or
    a squash, and a branch in no ref that this clone is known to have held: its recorded
    tip is here, or a reflog shows that it was renamed.
    Unknown: a branch in no ref with no such record. It can be a typo, a branch that
    comes later, a branch that is not fetched, or a branch in another clone.
    A renamed branch reads as its new name.
    """
    base = default_branch(root)
    cache: dict[tuple[str, str | None], str] = {}

    def read(branch: str, tip: str | None = None) -> str:
        key = (branch, tip)
        if key not in cache:
            can_end = base and branch != base
            cache[key] = _read_branch(root, branch, base, tip) if can_end else OPEN
        return cache[key]

    return read


def merged_checker(root: Path):
    """Return a cached function: is the work of this branch done?"""
    read = branch_reader(root)

    def is_merged(branch: str, tip: str | None = None) -> bool:
        return read(branch, tip) == DONE

    return is_merged


def branch_exists(root: Path, name: str) -> bool:
    """True for a local branch, or a remote copy named `far` or `origin/far`."""
    refs = _branch_refs(root)
    return refs is None or f"refs/heads/{name}" in refs or _has_remote_copy(refs, name)


def branch_tip(root: Path, name: str) -> str | None:
    """The commit of a local branch, else of a remote copy. None when no ref has the name."""
    out = run_git(
        root, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads", "refs/remotes"
    )
    tips = dict(line.split(" ", 1) for line in (out or "").splitlines())
    local = tips.get(f"refs/heads/{name}")
    return local or next((tip for ref, tip in tips.items() if _has_remote_copy([ref], name)), None)


def _branch_refs(root: Path) -> list[str] | None:
    """Every local and remote branch ref. None when git cannot say, which is not "no branch"."""
    out = run_git(root, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes")
    return None if out is None else out.splitlines()


def _has_remote_copy(refs: list[str], name: str) -> bool:
    remote = [r.removeprefix("refs/remotes/") for r in refs if r.startswith("refs/remotes/")]
    return any(name in (ref, ref.partition("/")[2]) for ref in remote)


def _renamed_to(root: Path, name: str) -> str | None:
    """The new name of a renamed branch, "" when there is none, None when git cannot say.

    It reads the reflogs, which git keeps for 90 days by default.
    """
    marker = f"Branch: renamed refs/heads/{name} to refs/heads/"
    log = run_git(
        root, "log", "-g", "--all", "--format=%gs", "--fixed-strings", f"--grep-reflog={marker}"
    )
    if log is None:
        return None
    lines = [line for line in log.splitlines() if line.startswith(marker)]
    return lines[0].removeprefix(marker) if lines else ""


def _checked_out(root: Path, branch: str) -> bool:
    """True when a worktree that still exists has this branch, or when git cannot say."""
    out = run_git(root, "worktree", "list", "--porcelain")
    if out is None:
        return True
    entries = [entry.splitlines() for entry in out.split("\n\n")]
    return any(
        f"branch refs/heads/{branch}" in lines
        and not any(line.startswith("prunable") for line in lines)
        for lines in entries
    )


def _read_branch(root: Path, branch: str, base: str, recorded: str | None) -> str:
    refs = _branch_refs(root)
    if refs is None:
        return OPEN
    seen = {branch}
    while f"refs/heads/{branch}" not in refs:
        if _has_remote_copy(refs, branch):
            return OPEN
        renamed = _renamed_to(root, branch)
        if renamed == "":
            return DONE if len(seen) > 1 or _commit_here(root, recorded) else UNKNOWN
        if renamed is None or renamed in seen:
            return OPEN
        seen.add(renamed)
        branch = renamed
    if branch == base or _checked_out(root, branch):
        return OPEN
    tip = run_git(root, "rev-parse", f"refs/heads/{branch}") or ""
    landed = (
        _made_commit_landed(root, branch, base)
        if _in_base(root, tip, base)
        else _squashed(root, tip, base)
    )
    return DONE if landed else OPEN


def _commit_here(root: Path, commit: str | None) -> bool:
    """True when this clone has the commit. Another clone's unpushed tip is not here."""
    return bool(commit) and run_git(root, "cat-file", "-e", f"{commit}^{{commit}}") is not None


def _in_base(root: Path, commit: str, base: str) -> bool:
    return run_git(root, "merge-base", "--is-ancestor", commit, base) is not None


# The reflog actions that make a new commit on the branch. A fast-forward, a reset and a
# create move a branch to a commit that was made elsewhere.
_MADE_HERE = ("commit", "cherry-pick:", "revert:", "am:")
_REFLOG_CHECKS = 20


def _made_commit_landed(root: Path, branch: str, base: str) -> bool:
    """True when the reflog shows a commit made on this branch, and it is in the base.

    A tip in the base proves nothing by itself: a new branch with no commits has one too.
    A rebase rewrites the commits that were made, so its result counts after one of them.
    """
    log = run_git(root, "log", "-g", "--format=%H %gs", f"refs/heads/{branch}") or ""
    commits, actions = [], []
    for line in log.splitlines():
        commit, _, action = line.partition(" ")
        commits.append(commit)
        actions.append(action)
    made = [i for i, a in enumerate(actions) if a.startswith(_MADE_HERE) or "Merge made" in a]
    if not made:
        return False
    rebased = [i for i, a in enumerate(actions[: made[-1]]) if a.startswith("rebase")]
    checks = sorted({*made, *rebased})[:_REFLOG_CHECKS]
    return any(_in_base(root, commits[i], base) for i in checks)


def _squashed(root: Path, tip: str, base: str) -> bool:
    """True when the branch changes something and a merge of it into the base changes nothing.

    Needs git 2.38. A commit copied with its author date and subject is a cherry-pick, not a
    squash, so that branch stays open.
    """
    merged = run_git(root, "merge-tree", "--write-tree", base, tip)
    tree = run_git(root, "rev-parse", f"{base}^{{tree}}")
    if not merged or merged.splitlines()[0] != tree:
        return False
    fork = run_git(root, "merge-base", base, tip)
    if not fork or run_git(root, "rev-parse", f"{tip}^{{tree}}") == run_git(
        root, "rev-parse", f"{fork}^{{tree}}"
    ):
        return False
    stamp = "--format=%ae %at %s"
    ours = run_git(root, "log", stamp, f"{fork}..{tip}")
    theirs = run_git(root, "log", stamp, f"{fork}..{base}")
    if ours is None or theirs is None:
        return False
    return not set(ours.splitlines()) & set(theirs.splitlines())
