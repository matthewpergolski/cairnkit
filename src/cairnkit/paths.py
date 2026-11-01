"""Find the project, its checkouts, and its memory folder."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from cairnkit import deadline

LINK_NAME = "memory-bank"
PATH_FILE = ".memory-path"
ENV_DIR = "MEMORY_DIR"
IDENTITY_FILE = ".identity"
RECORD_FILE = "cairnkit-memory"
_GIT_LOCATION_ENV = frozenset(
    {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX"}
)


@dataclass
class Project:
    """One project: the checkout we are in, the main checkout, and all worktrees.

    `home` holds .memory-path and names the default memory. It is the main checkout, or
    the bare repo when no main checkout exists. `main_root` is always a checkout.
    """

    root: Path
    main_root: Path
    checkouts: list[Path] = field(default_factory=list)
    common_dir: Path | None = None
    home: Path | None = None
    bare: bool = False

    def __post_init__(self) -> None:
        self.home = self.home or self.main_root

    @property
    def is_git(self) -> bool:
        return self.common_dir is not None


def run_git(
    cwd: Path, *args: str, timeout: float = 3.0, env: dict[str, str] | None = None
) -> str | None:
    """Run git. Return its output, or None when git fails, is missing or has no time left."""
    room = deadline.left()
    if room <= 0 or deadline.git_stuck():
        return None
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=min(timeout, room),
            env=env,
        )
    except subprocess.TimeoutExpired:
        if timeout <= room:
            deadline.note_git_timeout()
        return None
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
    first, bare, listed = _read_worktrees(root)
    home = first or root
    if home == common and not bare:
        # A submodule or a separate git dir: git lists its git dir, not its checkout.
        tree = run_git(common, "config", "core.worktree")
        home = Path(os.path.normpath(common / tree)) if tree else root
    checkouts = [home if path == common else path for path in listed] or [root]
    main_root = checkouts[0] if bare else home
    if main_root not in checkouts:
        checkouts.insert(0, main_root)
    return Project(
        root=root, main_root=main_root, checkouts=checkouts, common_dir=common, home=home, bare=bare
    )


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


def _read_worktrees(root: Path) -> tuple[Path | None, bool, list[Path]]:
    """Return git's first entry, whether it is a bare repo, and each checkout that exists."""
    out = run_git(root, "worktree", "list", "--porcelain")
    if not out:
        return None, False, []
    entries = [block.splitlines() for block in out.split("\n\n")]
    paths = [
        Path(lines[0].removeprefix("worktree "))
        for lines in entries
        if "bare" not in lines and not any(line.startswith("prunable") for line in lines)
    ]
    first = Path(entries[0][0].removeprefix("worktree "))
    return first, "bare" in entries[0], [p for p in paths if p.is_dir()]


def resolve_memory_dir(project: Project, flag: str | None = None) -> tuple[Path, str]:
    """Return the memory folder and where the setting came from.

    Order: flag, MEMORY_DIR, the .memory-path target when it holds a memory, a link that
    resolves to a memory, the place this repo last recorded, the .memory-path target, then
    the default folder. A name is only a guess, so a link or a record beats it.
    """
    if flag:
        return Path(flag).expanduser().absolute(), "flag"
    env = os.environ.get(ENV_DIR)
    if env:
        return Path(env).expanduser().absolute(), ENV_DIR
    named = _path_file_target(project)
    if named and holds_memory(named):
        return named, PATH_FILE
    linked = linked_memory(project)
    if linked:
        return linked, "link"
    recorded = _recorded_memory(project)
    if recorded:
        return recorded, "this repo's record"
    if named:
        return named, PATH_FILE
    return _default_memory_dir(project), "default"


def holds_memory(folder: Path) -> bool:
    return (folder / "facts").is_dir()


def _path_file_target(project: Project) -> Path | None:
    path_file = project.home / PATH_FILE
    if not path_file.is_file():
        return None
    lines = path_file.read_text().splitlines()
    first = lines[0].strip() if lines else ""
    if not first:
        return None
    target = Path(first).expanduser()
    if not target.is_absolute():
        target = project.home / target
    return Path(os.path.normpath(target))


def linked_memory(project: Project) -> Path | None:
    """The memory that an existing link resolves to. The main checkout's link goes first."""
    for checkout in [project.main_root, *project.checkouts]:
        link = checkout / LINK_NAME
        if link.is_symlink() and holds_memory(link):
            return link.resolve()
    return None


def read_identity(folder: Path) -> tuple[str, set[str]] | None:
    """A memory's id and the root commits of its project. None when the folder has no id."""
    try:
        lines = (folder / IDENTITY_FILE).read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or not lines[0].strip():
        return None
    return lines[0].strip(), set(lines[1].split()) if len(lines) > 1 else set()


def record_file(project: Project) -> Path | None:
    return project.common_dir / RECORD_FILE if project.common_dir else None


def _read_record(project: Project) -> tuple[str, Path] | None:
    """The memory id and the absolute path that this repo last saw."""
    path = record_file(project)
    try:
        lines = path.read_text().splitlines() if path else []
    except (OSError, UnicodeDecodeError):
        return None
    return (lines[0], Path(lines[1])) if len(lines) >= 2 else None


def _recorded_memory(project: Project) -> Path | None:
    """The memory with the recorded id: at its recorded place, or moved to a folder near it."""
    record = _read_record(project)
    if record is None:
        return None
    memory_id, place = record

    def is_it(folder: Path) -> bool:
        identity = read_identity(folder)
        return holds_memory(folder) and identity is not None and identity[0] == memory_id

    if is_it(place):
        return place
    for parent in dict.fromkeys((project.home.parent, place.parent)):
        for folder in _folders(parent):
            if is_it(folder):
                return folder
    return None


def _folders(parent: Path) -> list[Path]:
    try:
        return sorted(p for p in parent.iterdir() if p.is_dir())
    except OSError:
        return []


def tree_env() -> dict[str, str]:
    """The environment for git in a folder that the caller names.

    A git hook sets GIT_DIR. With it, git reads that repo and calls the current folder its
    top, whichever folder that is.
    """
    return {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_ENV}


def enclosing_trees(folder: Path) -> list[Path]:
    """Every git work tree that holds this folder, nearest first."""
    trees: list[Path] = []
    here = folder.resolve()
    while True:
        while not here.is_dir():
            here = here.parent
        top = run_git(here, "rev-parse", "--show-toplevel", env=tree_env())
        if not top:
            return trees
        trees.append(Path(top))
        if Path(top).parent == Path(top):
            return trees
        here = Path(top).parent


def _default_memory_dir(project: Project) -> Path:
    home = project.home
    if project.bare:
        # In the layout proj/.bare the worktrees sit beside it, and proj names the project.
        stem = home.parent.name if home.name.startswith(".") else home.name.removesuffix(".git")
        return home.parent / f"{stem}.memory"
    sibling = home.parent / f"{home.name}.memory"
    if holds_memory(sibling):
        return sibling
    trees = enclosing_trees(home.parent)
    if not trees or not os.access(trees[-1].parent, os.W_OK):
        return sibling
    # A folder inside a work tree can be committed by `git add -A` or deleted by `git clean`.
    outermost = trees[-1]
    path = home.resolve().relative_to(outermost)
    return outermost.parent / f"{'.'.join((outermost.name, *path.parts))}.memory"


@dataclass
class LostMemory:
    """What this project knows about a memory that it cannot reach."""

    gone: Path | None
    found: list[Path]
    default: Path


def lost_memory(project: Project) -> LostMemory | None:
    """Read only. None means that nothing shows that this project had a memory."""
    gone = _dangling_target(project)
    if gone is None:
        record = _read_record(project)
        gone = record[1] if record else None
    found = _unclaimed_memories(project)
    if gone is None and not found:
        return None
    return LostMemory(gone, found, _default_memory_dir(project))


def lost_note(lost: LostMemory) -> str:
    """Say what is known and the one command that is needed. Never advise a bare init."""
    start = f"To start a new memory instead: `memory init --path {lost.default}`."
    parts = [f"This project's memory was at {lost.gone}, and it is not there."] if lost.gone else []
    if lost.found:
        names = " or ".join(f"`memory init --path {folder}`" for folder in lost.found)
        parts.append(f"A memory with no project was found. If it is this project's: {names}.")
    else:
        parts.append("If you moved it, run `memory init --path NEW_PLACE`.")
    return " ".join([*parts, start])


def _dangling_target(project: Project) -> Path | None:
    for checkout in [project.main_root, *project.checkouts]:
        link = checkout / LINK_NAME
        if link.is_symlink() and not link.exists():
            return Path(os.path.normpath(checkout / os.readlink(link)))
    return None


def _unclaimed_memories(project: Project) -> list[Path]:
    """Folders beside the project that look like a memory, and that nothing else claims.

    A memory whose project folder still exists has its owner. A memory that names root
    commits with none in common with this repo belongs to another project.
    """
    ours = root_commits(project)
    found = []
    for folder in _folders(project.home.parent):
        if not holds_memory(folder) or not (folder / "config.toml").is_file():
            continue
        if folder.name.endswith(".memory") and folder.with_suffix("").is_dir():
            continue
        identity = read_identity(folder)
        if identity and identity[1] and ours and not identity[1] & ours:
            continue
        found.append(folder)
    return found


def root_commits(project: Project) -> set[str]:
    if not project.is_git:
        return set()
    return set((run_git(project.root, "rev-list", "--max-parents=0", "HEAD") or "").split())


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
