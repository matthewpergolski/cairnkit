"""Find the project, its checkouts, and its memory folder."""

from __future__ import annotations

import atexit
import contextlib
import functools
import os
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from cairnkit import deadline, plainfile
from cairnkit.selection import clean_path, shell_word

LINK_NAME = "memory-bank"
PATH_FILE = ".memory-path"
ENV_DIR = "MEMORY_DIR"
IDENTITY_FILE = ".identity"
RECORD_FILE = "cairnkit-memory"
COPY_NOTED_FILE = "cairnkit-copy-noted"
SHARED_SETTING = "cairnkit.sharedmemory"
NOT_EARLIER_SETTING = "cairnkit.notearlier"
UNREAD_WRITER = "branch-unread"
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


_INDEX_COPIES: dict[tuple[str, int, int], str] = {}
_INDEX_PATHS: dict[tuple[str, str], str] = {}


def _drop_index_copies() -> None:
    for path in _INDEX_COPIES.values():
        for name in (path, f"{path}.lock"):
            with contextlib.suppress(OSError):
                os.unlink(name)


class NotPrivate(OSError):
    """The folder for index copies is a link, or another user owns it or can write in it."""


def _mine(info: os.stat_result) -> bool:
    """True when this user owns the file. A platform with no user ids, such as Windows, has no
    other user to compare, so there it is always true."""
    getuid = getattr(os, "getuid", None)
    return getuid is None or info.st_uid == getuid()


def _copies_folder() -> Path:
    """One folder for the index copies. A copy of a killed hook is gone after an hour there.

    The temp folder can be shared, so another user can make this name first. Only a real folder
    that this user owns, with no access for others, is used or cleaned.
    """
    getuid = getattr(os, "getuid", None)
    folder = Path(tempfile.gettempdir()) / f"cairnkit-index-{getuid() if getuid else 'user'}"
    folder.mkdir(mode=0o700, exist_ok=True)
    info = os.lstat(folder)
    if not stat.S_ISDIR(info.st_mode) or not _mine(info) or info.st_mode & 0o077:
        raise NotPrivate(f"not a private folder: {folder}")
    limit = time.time() - 3600
    with os.scandir(folder) as entries:
        for old in entries:
            with contextlib.suppress(OSError):
                if (
                    old.is_file(follow_symlinks=False)
                    and old.stat(follow_symlinks=False).st_mtime < limit
                ):
                    os.unlink(old.path)
    return folder


def _index_copy(cwd: Path, env: dict[str, str]) -> str | None:
    """A copy of the index that git uses in `cwd`, for a `git diff` to refresh in place of it.

    Never raises: with no copy, the diff runs on the real index.
    """
    with contextlib.suppress(Exception):
        where = (str(cwd), env.get("GIT_INDEX_FILE", ""))
        if where not in _INDEX_PATHS:
            found = subprocess.run(
                ["git", "rev-parse", "--path-format=absolute", "--git-path", "index"],
                cwd=cwd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=max(min(1.0, deadline.left()), 0.01),
                env=env,
            )
            _INDEX_PATHS[where] = found.stdout.strip() if found.returncode == 0 else ""
        real = Path(_INDEX_PATHS[where]) if _INDEX_PATHS[where] else None
        if real and real.is_file():
            info = real.stat()
            key = (str(real), info.st_mtime_ns, info.st_size)
            if key not in _INDEX_COPIES:
                if not _INDEX_COPIES:
                    atexit.register(_drop_index_copies)
                fd, path = tempfile.mkstemp(prefix="index-", dir=_copies_folder())
                try:
                    with os.fdopen(fd, "wb") as fh:
                        fh.write(plainfile.read_bytes(real))
                except BaseException:  # a hook's time budget can end it here
                    with contextlib.suppress(OSError):
                        os.unlink(path)
                    raise
                _INDEX_COPIES[key] = path
            return _INDEX_COPIES[key]
    return None


def run_git(
    cwd: Path, *args: str, timeout: float = 3.0, env: dict[str, str] | None = None
) -> str | None:
    """Run git. Return its output, or None when git fails, is missing or has no time left.

    A git that runs past its time is killed, and a lock that it held stays and stops the next
    commit. A read such as `git status` takes no optional lock here. A `git diff` against the
    worktree always refreshes and writes the index, so it gets a copy of the index.
    """
    room = deadline.left()
    if room <= 0 or deadline.git_stuck():
        deadline.note_git_cut()
        return None
    env = {**(env if env is not None else os.environ), "GIT_OPTIONAL_LOCKS": "0"}
    if args and args[0] == "diff":
        copy = _index_copy(cwd, env)
        if copy:
            env["GIT_INDEX_FILE"] = copy
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=min(timeout, room),
            env=env,
        )
    except subprocess.TimeoutExpired:
        deadline.note_git_cut()
        if timeout <= room:
            deadline.note_git_timeout()
        return None
    except (OSError, subprocess.SubprocessError):
        deadline.note_git_cut()
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def find_project(cwd: Path | None = None) -> Project:
    cwd = Path(cwd or Path.cwd()).absolute()
    cuts = deadline.git_cuts()
    top = run_git(cwd, "rev-parse", "--show-toplevel")
    if top is None:
        found = _repo_above(cwd) if deadline.git_cuts() > cuts else None
        if found:
            return Project(
                root=found[0], main_root=found[0], checkouts=[found[0]], common_dir=found[1]
            )
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


def inside_git_folder(cwd: Path) -> bool:
    """True in a bare repo or in a .git folder. No setup belongs there, because no checkout is."""
    return run_git(cwd, "rev-parse", "--is-inside-git-dir") == "true"


GIT_FOLDER_REFUSAL = (
    "error: {cwd} is a git folder, not a checkout. Nothing changed. Run this in a checkout. "
    "For a bare repo, add a worktree first: `git worktree add ../NAME`."
)


def _git_dir(folder: Path) -> Path | None:
    """The git dir of this checkout, read with no git. None when `.git` here holds no repo."""
    marker = folder / ".git"
    try:
        if marker.is_file():
            marker = folder / plainfile.read_text(marker).removeprefix("gitdir:").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return marker if (marker / "HEAD").is_file() else None


def _repo_above(cwd: Path) -> tuple[Path, Path] | None:
    """(root, common git dir) when git gave no answer: a timeout does not mean "no repo"."""
    for folder in (cwd, *cwd.parents):
        found = _git_dir(folder)
        if found:
            try:
                shared = plainfile.read_text(found / "commondir").strip()
            except (OSError, UnicodeDecodeError):
                shared = "."
            return folder, Path(os.path.normpath(found / shared))
    return None


def plain_root(cwd: Path) -> Path:
    """Outside git: the nearest folder, from cwd up, with a memory link or .memory-path.

    The walk does not check the home folder or the file system root, so one
    stray link there cannot catch every folder. With no match, cwd is the root.
    """
    stops = {Path.home().absolute(), Path(cwd.anchor)}
    folder = cwd
    while folder not in stops:
        link, path_file = folder / LINK_NAME, folder / PATH_FILE
        if (link.is_symlink() and _owner_put(None, link)) or (
            path_file.is_file() and _owner_put(None, path_file)
        ):
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
    return default_memory_dir(project), "default"


def holds_memory(folder: Path) -> bool:
    return (folder / "facts").is_dir()


def _path_file_target(project: Project) -> Path | None:
    path_file = project.home / PATH_FILE
    if not path_file.is_file() or not _owner_put(project, path_file):
        return None
    try:
        lines = plainfile.read_text(path_file).splitlines()
    except (OSError, UnicodeDecodeError):
        return None
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
        if link.is_symlink() and holds_memory(link) and _owner_put(project, link):
            return link.resolve()
    return None


def _owner_put(project: Project | None, path: Path) -> bool:
    """True for a pointer that the owner put here: a file of this user that git does not track.

    A file that git tracks came with the repo, from anyone who can commit to it. A file of another
    user, such as one in a shared folder outside git, came from that user.
    """
    try:
        if not _mine(path.lstat()):
            return False
    except OSError:
        return False
    return project is None or not project.is_git or pointer_tracked(path) is False


def tracked_pointers(project: Project) -> list[Path]:
    """The pointers that the memory search reads and git tracks. None of them counts.

    The search reads `.memory-path`, then each link up to the first one that it uses.
    """
    if not project.is_git:
        return []
    found = [project.home / PATH_FILE] if (project.home / PATH_FILE).is_file() else []
    for checkout in dict.fromkeys([project.main_root, *project.checkouts]):
        link = checkout / LINK_NAME
        if link.is_symlink():
            found.append(link)
            if holds_memory(link) and pointer_tracked(link) is False:
                break
    return [path for path in found if pointer_tracked(path) is not False]


class Identity(NamedTuple):
    """What a memory says about itself. A memory from before the owner line has no owner."""

    id: str
    roots: set[str]
    owner: Path | None


class Record(NamedTuple):
    """What a repo says about its memory. A record from before the repo line has no repo."""

    id: str
    place: Path
    repo: Path | None


def read_identity(folder: Path) -> Identity | None:
    """A memory's id, its project's root commits and its owner. None when it has no id."""
    try:
        lines = plainfile.read_text(folder / IDENTITY_FILE).splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if not lines or not lines[0].strip():
        return None
    roots = set(lines[1].split()) if len(lines) > 1 else set()
    return Identity(lines[0].strip(), roots, Path(lines[2]) if len(lines) > 2 else None)


def write_identity(folder: Path, identity: Identity) -> None:
    """Replace the file whole, so a reader never sees half of it."""
    roots = " ".join(sorted(identity.roots))
    temp = plainfile.inside(folder, folder / f"{IDENTITY_FILE}.{os.getpid()}")
    plainfile.write_text(temp, f"{identity.id}\n{roots}\n{identity.owner}\n")
    os.replace(temp, folder / IDENTITY_FILE)


def project_key(project: Project) -> Path:
    """The one path that names this project in each of its checkouts."""
    return (project.common_dir or project.home).resolve()


def record_file(project: Project) -> Path | None:
    return project.common_dir / RECORD_FILE if project.common_dir else None


def _read_record(project: Project) -> Record | None:
    """The memory that this repo last saw."""
    path = record_file(project)
    try:
        lines = plainfile.read_text(path).splitlines() if path else []
    except (OSError, UnicodeDecodeError):
        return None
    if len(lines) < 2:
        return None
    return Record(lines[0], Path(lines[1]), Path(lines[2]) if len(lines) > 2 else None)


def recorded_repo(project: Project) -> Path:
    """The repo that this repo's record names. A copied or a moved repo brings the first one's."""
    record = _read_record(project)
    return record.repo if record and record.repo else project_key(project)


def _has_id(folder: Path, memory_id: str) -> bool:
    identity = read_identity(folder)
    return holds_memory(folder) and identity is not None and identity.id == memory_id


def _same_id_folders(project: Project, record: Record) -> list[Path]:
    """The folders near the project or the old place that hold a memory with the recorded id."""
    parents = dict.fromkeys((project.home.parent, record.place.parent))
    return [f for parent in parents for f in _folders(parent) if _has_id(f, record.id)]


def _recorded_memory(project: Project) -> Path | None:
    """The memory with the recorded id, at its recorded place or moved under an expected name.

    A copy has the same id, so the id alone cannot tell the real memory from an old backup.
    With more than one, or with a name that nothing expects, a person or agent must choose.
    """
    record = _read_record(project)
    if record is None:
        return None
    if _has_id(record.place, record.id):
        return record.place
    found = _same_id_folders(project, record)
    expected = {
        record.place.name,
        f"{project.home.name}.memory",
        default_memory_dir(project).name,
    }
    return found[0] if len(found) == 1 and found[0].name in expected else None


OURS, COPY, ANOTHER, UNCLAIMED = "ours", "copy", "another", "unclaimed"


def _still_uses(owner: Path, memory_id: str, memdir: Path) -> bool:
    """True when the project at `owner` still exists and still uses this folder.

    A copy of a memory has the same id, so the place in the record tells the two apart.
    """
    try:
        lines = plainfile.read_text(owner / RECORD_FILE).splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    if lines:
        return lines[0] == memory_id and lines[1:2] in ([], [str(memdir.resolve())])
    link = owner / LINK_NAME
    return link.is_symlink() and link.resolve() == memdir.resolve()


def owner_state(project: Project, memdir: Path) -> tuple[str, Path | None]:
    """Whose memory this is: (OURS, None), (COPY, owner), (ANOTHER, owner, when known) or
    (UNCLAIMED, the owner that left).

    A move and a copy look alike from inside a repo, so with its owner gone, this memory belongs
    to no repo until one of them takes it with `memory init`, unless its root commits say that it
    belongs to another history. The usual call reads two small files and runs no git.
    """
    identity = read_identity(memdir)
    here = project_key(project)
    if identity is None or identity.owner == here:
        return OURS, None
    if identity.owner and _still_uses(identity.owner, identity.id, memdir):
        record = _read_record(project)
        copied = record and record.id == identity.id and record.repo not in (None, here)
        return (COPY if copied else ANOTHER), identity.owner
    ours = root_commits(project)
    if identity.roots and ours and not identity.roots & ours:
        return ANOTHER, None
    return (UNCLAIMED, identity.owner) if identity.owner else (OURS, None)


def _repo_of(key: Path) -> Path:
    return key.parent if key.name == ".git" else key


def _shown(owner: Path | None) -> str:
    return f"another project ({clean_path(_repo_of(owner))})" if owner else "another project"


def _other_claimants(project: Project, memdir: Path, gone: Path) -> list[Path]:
    """Repos beside this one or beside the gone owner whose record names this memory."""
    identity = read_identity(memdir)
    here = project_key(project)
    parents = dict.fromkeys((project.home.parent, _repo_of(gone).parent))
    return [
        folder
        for parent in parents
        for folder in _folders(parent)
        if (folder / ".git").resolve() != here and _still_uses(folder / ".git", identity.id, memdir)
    ]


def _keep_apart(project: Project, memdir: Path) -> str:
    """The command for a memory of this repo that keeps these facts."""
    place = default_memory_dir(project)
    if place.exists():
        place = place.with_name(f"{project.home.name}-own.memory")
    old, new = shell_word(memdir), shell_word(place)
    return f"`cp -R {old} {new} && memory init --path {new}`"


def owner_line(project: Project, memdir: Path) -> str | None:
    """The one line that says this memory belongs to another project. None when it does not."""
    state, owner = owner_state(project, memdir)
    if state == OURS:
        return None
    if state == COPY:
        return (
            f"note: {clean_path(memdir)} belongs to {_shown(owner)}, and this repo holds a "
            "record from before "
            "a copy or a move. What you add here goes there. To keep these facts in a memory of "
            f"this repo: {_keep_apart(project, memdir)}."
        )
    if project.is_git and (
        run_git(project.root, "config", "--local", "--bool", "--get", SHARED_SETTING) == "true"
    ):
        return None
    if state == UNCLAIMED:
        others = _other_claimants(project, memdir, owner)
        if not others:
            return None
        names = " and ".join(clean_path(folder) for folder in others)
        return (
            f"note: {clean_path(memdir)} was set up by {clean_path(_repo_of(owner))}, "
            "which is gone, and "
            f"{names} also "
            "uses it. Each can be that repo moved or a copy of it, so each reads and writes its "
            "facts. `memory init` in the repo that keeps it takes it. To keep these facts in a "
            f"memory of this repo: {_keep_apart(project, memdir)}."
        )
    share = f" To share on purpose: `git config {SHARED_SETTING} true`." if project.is_git else ""
    return (
        f"note: {clean_path(memdir)} belongs to {_shown(owner)}, so both projects read and write "
        "its facts. For a memory of its own: "
        f"`memory init --path {shell_word(default_memory_dir(project))}`.{share}"
    )


def copy_line_once(project: Project, memdir: Path) -> str | None:
    """The line for a copied or a moved repo, the first time only in each state."""
    state = owner_state(project, memdir)[0]
    line = owner_line(project, memdir) if state in (COPY, UNCLAIMED) else None
    if line is None or not project.is_git:
        return None
    marker = project_key(project) / COPY_NOTED_FILE
    noted = f"{project_key(project)} {state}"
    try:
        if plainfile.read_text(marker) == noted:  # a second copy brings this file along
            return None
    except (OSError, UnicodeDecodeError):
        pass
    with contextlib.suppress(OSError):
        plainfile.write_text(marker, noted)
    return line


def load_owner_line(project: Project, memdir: Path) -> str | None:
    """Each load says it, unless this is a copied or a moved repo, which hears it once."""
    if owner_state(project, memdir)[0] in (COPY, UNCLAIMED):
        return copy_line_once(project, memdir)
    return owner_line(project, memdir)


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


_LISTED: dict[tuple[str, str, int, int], bool] = {}
_INDEX_READ_LIMIT = 64 * 1024 * 1024
_FULL_PATH_INDEXES = (b"\0\0\0\x02", b"\0\0\0\x03")


def _index_may_list(git_dir: Path, rel: str) -> bool:
    """False only when the index file shows, with no git, that it lists neither rel nor a path
    under it.

    Index versions 2 and 3 hold each path in full. A split index (extension "link"), a sparse
    index ("sdir"), version 4 or a name that is not ASCII can hide a path, so then git must say.
    """
    if not rel.isascii():
        return True
    try:
        data = plainfile.read_bytes(git_dir / "index", limit=_INDEX_READ_LIMIT)
    except OSError:
        return True
    if data[:4] != b"DIRC" or data[4:8] not in _FULL_PATH_INDEXES:
        return True
    if b"link" in data or b"sdir" in data:
        return True
    name = rel.encode()
    return name + b"\0" in data or name + b"/" in data


def git_lists(tree: Path, rel: str) -> bool | None:
    """True when git in the work tree `tree` tracks rel or a file under it. None when git cannot
    say. The tree is the top of a checkout, and only its own index counts.

    The index file answers a "no" with no git where it can. Each answer is kept until the index
    changes, so a hook seldom runs git for it.
    """
    git_dir = _git_dir(tree)
    if git_dir is None:
        return False  # not the top of a checkout, such as a bare repo: no index of its own
    try:
        info = (git_dir / "index").stat()
    except FileNotFoundError:
        return False  # git makes the index at the first add
    except OSError:
        return None
    key = (str(tree), rel, info.st_mtime_ns, info.st_size)
    if key not in _LISTED:
        if _index_may_list(git_dir, rel):
            listed = run_git(tree, "--literal-pathspecs", "ls-files", "--", rel, env=tree_env())
            if listed is None:
                return None
            _LISTED[key] = bool(listed)
        else:
            _LISTED[key] = False
    return _LISTED[key]


def pointer_tracked(path: Path) -> bool | None:
    """Whether git tracks this `.memory-path` or `memory-bank`. None when git cannot say.

    A pointer sits at the top of a checkout, so only that checkout's index counts. A repo
    above it, such as a home folder kept in git, does not choose this project's memory.
    """
    return git_lists(path.parent, path.name)


def memory_tracked_by(folder: Path) -> Path | None:
    """The work tree of a repo above the memory folder that tracks it or a file in it.

    A repo at the memory folder or inside it does not count: an owner may keep the memory
    folder in a git repo of its own, which no project shares. When git cannot say, None.
    """
    real = Path(os.path.realpath(folder))
    for tree in real.parents:
        if _git_dir(tree) is not None and git_lists(tree, real.relative_to(tree).as_posix()):
            return tree
    return None


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


def default_memory_dir(project: Project) -> Path:
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
    """Read only. None means that nothing shows that this project had a memory.

    `gone` is proof that it had one. `found` alone is only a folder that could be its memory.
    """
    record = _read_record(project)
    gone = _dangling_target(project) or (record.place if record else None)
    found = _same_id_folders(project, record) if record else []
    found = found or _earlier_memories(project)
    if gone is None and not found:
        return None
    return LostMemory(gone, found, default_memory_dir(project))


def earlier_note(found: list[Path]) -> str:
    """One short note. It names only a folder under a name this project is known to have had."""
    commands = " or ".join(f"`memory init --path {shell_word(folder)}`" for folder in found)
    return f"A memory beside this project could be its own under an earlier name: {commands}."


def beside_line(project: Project, memdir: Path) -> str | None:
    """Said at each load and check until the folder is adopted, denied or gone."""
    found = [f for f in _earlier_memories(project) if f.resolve() != memdir.resolve()]
    if not found:
        return None
    deny = " and ".join(
        f"`git config --add {NOT_EARLIER_SETTING} {clean_path(f.name)}`" for f in found
    )
    return f"note: {earlier_note(found)} If not: {deny}."


def lost_note(lost: LostMemory) -> str:
    """Say what is known and the one command that is needed."""
    if lost.gone is None:
        return f"{earlier_note(lost.found)} If not, run `memory init`."
    # A bare init would hide a memory that this project is known to have.
    parts = [f"This project's memory was at {clean_path(lost.gone)}, and it is not there."]
    if lost.found:
        names = " or ".join(f"`memory init --path {shell_word(folder)}`" for folder in lost.found)
        parts.append(f"Found, and each can be an old copy, so choose the newest: {names}.")
    else:
        parts.append("If you moved it, run `memory init --path NEW_PLACE`.")
    parts.append(f"To start a new memory instead: `memory init --path {shell_word(lost.default)}`.")
    return " ".join(parts)


def _dangling_target(project: Project) -> Path | None:
    for checkout in [project.main_root, *project.checkouts]:
        link = checkout / LINK_NAME
        if link.is_symlink() and not link.exists():
            return Path(os.path.normpath(checkout / os.readlink(link)))
    return None


def _known_names(project: Project) -> set[str]:
    """Names this project is known to have had: in its record, and its remote's last part."""
    record = _read_record(project)
    names = {record.place.name.removesuffix(".memory")} if record else set()
    if record and record.repo:
        names.add(_repo_of(record.repo).name)
    url = run_git(project.root, "config", "--local", "--get", "remote.origin.url")
    if url:
        names.add(url.rstrip("/").replace(":", "/").rpartition("/")[2].removesuffix(".git"))
    return names


def _earlier_memories(project: Project) -> list[Path]:
    """Memories beside the project under a name that it is known to have had.

    Only `<name>.memory` with no folder `<name>` fits. An owner that still uses the memory rules
    it out, and so do root commits that this repo lacks. An empty repo has no root commits, so
    no memory that had commits can be its own. A local setting can deny a folder by name.
    """
    orphans = [
        folder
        for folder in _folders(project.home.parent)
        if folder.name.endswith(".memory")
        and not folder.with_suffix("").is_dir()
        and holds_memory(folder)
        and (folder / "config.toml").is_file()
    ]
    if not orphans or not project.is_git:
        return []
    names = _known_names(project)
    orphans = [folder for folder in orphans if folder.with_suffix("").name in names]
    if not orphans:
        return []
    denied = run_git(project.root, "config", "--local", "--get-all", NOT_EARLIER_SETTING) or ""
    ours = root_commits(project)
    found = []
    for folder in orphans:
        if folder.name in denied.splitlines():
            continue
        identity = read_identity(folder)
        if identity and identity.owner and _still_uses(identity.owner, identity.id, folder):
            continue
        if identity and identity.roots and not identity.roots & ours:
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
    return name or _branch_from_files(root)


def _branch_from_files(root: Path) -> str | None:
    """The branch that the git dir names: a rebase's branch, else HEAD's. This needs no git."""
    folder = _git_dir(root)
    if folder is None:
        return None
    for path in (
        folder / "rebase-merge/head-name",
        folder / "rebase-apply/head-name",
        folder / "HEAD",
    ):
        try:
            text = plainfile.read_text(path).strip().removeprefix("ref: ")
        except (OSError, UnicodeDecodeError):
            continue
        # A reftable repo keeps this placeholder in HEAD.
        name = text.removeprefix("refs/heads/")
        return None if name == text or name == ".invalid" else name
    return None


def writer_name(root: Path) -> str:
    """The writer is MEMORY_WRITER, else the branch name, else `main`.

    In a repo where git gave no answer and the files name no branch, the name says so. Such a
    note must not land on `main`, because no session on another branch would see it.
    """
    cuts = deadline.git_cuts()
    name = os.environ.get("MEMORY_WRITER") or current_branch(root)
    if not name:
        name = UNREAD_WRITER if deadline.git_cuts() > cuts and _git_dir(root) else "main"
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
# Work can land here first. A branch that merges only into another branch has not landed.
INTEGRATION_BRANCHES = ("dev", "develop")
_SAME_CHANGE_CHECKS = 30
_SAME_CHANGE_FILES = 100


def branch_reader(root: Path):
    """Return a cached function: (branch, recorded tip) to OPEN, DONE or UNKNOWN.

    A false end is worse than a stale note, so each read needs evidence.

    Work lands in the default branch or an integration branch, local or on `origin`.
    Open: a branch checked out in a worktree, a remote copy whose work did not land,
    and a branch whose reflog shows no commit of its own in a base.
    Done: a branch that is not checked out and whose own commits landed by a merge or a squash,
    a remote copy with no local branch whose tip a squash or a merge commit took, and a branch in
    no ref whose recorded tip landed, or that a reflog shows was renamed.
    Unknown: a branch in no ref with no such record. It can be a typo, a branch that comes later,
    a branch that is not fetched, a branch in another clone, or a branch deleted with work that
    did not land. A renamed branch reads as its new name.
    """
    base = functools.cache(lambda: default_branch(root))
    cache: dict[tuple[str, str | None], str] = {}

    def read(branch: str, tip: str | None = None) -> str:
        key = (branch, tip)
        if key not in cache:
            can_end = base() and branch != base()
            cache[key] = _read_branch(root, branch, base(), tip) if can_end else OPEN
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


def _remote_copies(refs: list[str], name: str) -> list[str]:
    remote = [r for r in refs if r.startswith("refs/remotes/")]
    return [
        ref
        for ref in remote
        if name in ((short := ref.removeprefix("refs/remotes/")), short.partition("/")[2])
    ]


def _has_remote_copy(refs: list[str], name: str) -> bool:
    return bool(_remote_copies(refs, name))


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


def _bases(root: Path, branch: str, default: str) -> list[str]:
    """The refs where work lands, one for each commit: local and `origin` copies, not `branch`."""
    names = {name for name in (default, *INTEGRATION_BRANCHES) if name != branch}
    wanted = [f"refs/heads/{n}" for n in names] + [f"refs/remotes/origin/{n}" for n in names]
    out = run_git(root, "for-each-ref", "--format=%(objectname) %(refname)", *wanted) or ""
    by_commit = dict(line.split(" ", 1) for line in out.splitlines())
    return sorted(by_commit.values())


def _read_branch(root: Path, branch: str, base: str, recorded: str | None) -> str:
    refs = _branch_refs(root)
    if refs is None:
        return OPEN
    seen = {branch}
    while f"refs/heads/{branch}" not in refs:
        copies = _remote_copies(refs, branch)
        if copies:
            bases = _bases(root, branch, base)
            landed = all(any(_copy_landed(root, c, b) for b in bases) for c in copies)
            return DONE if landed else OPEN
        renamed = _renamed_to(root, branch)
        if renamed == "":
            if len(seen) > 1:
                return DONE
            return DONE if _recorded_landed(root, recorded, _bases(root, branch, base)) else UNKNOWN
        if renamed is None or renamed in seen:
            return OPEN
        seen.add(renamed)
        branch = renamed
    if branch == base or _checked_out(root, branch):
        return OPEN
    tip = run_git(root, "rev-parse", f"refs/heads/{branch}") or ""
    return DONE if any(_landed(root, branch, tip, b) for b in _bases(root, branch, base)) else OPEN


def _landed(root: Path, branch: str, tip: str, base: str) -> bool:
    if _in_base(root, tip, base):
        return _made_commit_landed(root, branch, base)
    return _squashed(root, tip, base)


def _copy_landed(root: Path, ref: str, base: str) -> bool:
    """A remote copy has no reflog of its work, so a tip in the base needs a merge that names it."""
    tip = run_git(root, "rev-parse", ref) or ""
    if not _in_base(root, tip, base):
        return _squashed(root, tip, base)
    merges = run_git(root, "log", "--merges", "--format=%P", f"{tip}..{base}") or ""
    return any(tip in line.split()[1:] for line in merges.splitlines())


def _recorded_landed(root: Path, recorded: str | None, bases: list[str]) -> bool:
    """A gone branch ended if its recorded commit landed. A commit that did not is live work."""
    if not recorded or not _commit_here(root, recorded):
        return False
    return any(_in_base(root, recorded, b) or _squashed(root, recorded, b) for b in bases)


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
    """True when the branch changes something and the base holds that change.

    The base holds it when a merge of the branch changes nothing (needs git 2.38), or when one
    commit there makes the same change, for a base that changed those lines later. A commit copied
    with its author date and subject is a cherry-pick, not a squash, so that branch stays open.
    """
    fork = run_git(root, "merge-base", base, tip)
    if not fork or run_git(root, "rev-parse", f"{tip}^{{tree}}") == run_git(
        root, "rev-parse", f"{fork}^{{tree}}"
    ):
        return False
    stamp = "--format=%ae %at %s"
    ours = run_git(root, "log", stamp, f"{fork}..{tip}")
    theirs = run_git(root, "log", stamp, f"{fork}..{base}")
    if ours is None or theirs is None or set(ours.splitlines()) & set(theirs.splitlines()):
        return False
    merged = run_git(root, "merge-tree", "--write-tree", base, tip)
    if merged and merged.splitlines()[0] == run_git(root, "rev-parse", f"{base}^{{tree}}"):
        return True
    return _same_change(root, fork, tip, base)


def _changed_lines(diff: str) -> list[str]:
    """The added and removed lines. Context and line numbers move when the base moves."""
    return [line for line in diff.splitlines() if line[:1] in ("+", "-")]


def _same_change(root: Path, fork: str, tip: str, base: str) -> bool:
    """True when one recent commit of the base makes the whole change of the branch."""
    want = _changed_lines(run_git(root, "diff", "--no-ext-diff", "--no-color", fork, tip) or "")
    files = (run_git(root, "diff", "--name-only", fork, tip) or "").splitlines()
    if not want or not files:
        return False
    log = run_git(
        root,
        "log",
        "-p",
        "--full-diff",
        "--no-ext-diff",
        "--no-color",
        "--format=%x00",
        f"-{_SAME_CHANGE_CHECKS}",
        f"{fork}..{base}",
        "--",
        *files[:_SAME_CHANGE_FILES],
    )
    return any(_changed_lines(commit) == want for commit in (log or "").split("\0"))
