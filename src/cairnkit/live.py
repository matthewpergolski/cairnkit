"""What other work is live in this project, for the load.

Git says which checkouts hold uncommitted changes. One marker for each session and checkout says
where a session is at work: `.sessions/live/<session>-<checkout>` holds the path, and its file time
is the last hook event there. A stop removes the markers of its session, so a session that ended
costs no words. Time ends the marker of a session that died in a turn. Markers are one small file
each because subagents share a session key, and a shared JSON file would lose their writes.

A helper with no recorded end gets its own line, with its purpose (`helpers.py`) and the state of
its own checkout, so a session killed in a turn leaves why it started the helper.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path, PurePath

from cairnkit import deadline, helpers, plainfile
from cairnkit.beforeshell import SETTING, _core_words, _parts, _words, take_once
from cairnkit.load import note_head
from cairnkit.memory import Memory
from cairnkit.paths import run_git, tree_env
from cairnkit.secretscan import mask
from cairnkit.selection import FRAME_HEADER, clean, load_text, name
from cairnkit.session import is_junk_path, is_memory_path
from cairnkit.state import effective_status

WORKING_SECONDS = 1800
# Of the load's budget, for all checkouts together. A slow checkout must not delay the session.
BUDGET = 1.5
# Past BUDGET, so that a slow checkout is a cut and not a stuck git for the steps after the load.
GIT_TIMEOUT = BUDGET * 2
MAX_CHECKOUTS = 12
MAX_LINES = 3
MAX_FILES = 5
MAX_HELPERS = 3
NOTE_WORDS = 20
# Options of git before its command that take a value as the next word.
GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
# Words in front of a command that run it as it is, with their options and settings.
RUN_AS = frozenset({"sudo", "env"})
ORDER = (
    "Live work that this session did not start is listed under `## Live work`. Do not commit, "
    "discard or remove it, also in a general tidy-up, unless the owner names that checkout or "
    "file. Leave it, and report that you left it."
)


@dataclass(frozen=True)
class Checkout:
    path: Path
    branch: str | None
    files: list[str]
    seen_at: float | None


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _folder(memory: Memory) -> Path:
    return memory.dir / ".sessions" / "live"


def note_working(memory: Memory, session: str) -> None:
    root = str(memory.project.root)
    folder = plainfile.inside(memory.dir, _folder(memory))
    folder.mkdir(parents=True, exist_ok=True)
    marker = plainfile.inside(memory.dir, folder / f"{_key(session)}-{_key(root)}")
    plainfile.write_text(marker, root, encoding="utf-8")


def clear_working(memory: Memory, session: str) -> list[str]:
    """Remove the markers of a session. Return the checkouts that they named."""
    paths = []
    for marker in plainfile.files_in(memory.dir, _folder(memory), f"{_key(session)}-*"):
        with contextlib.suppress(OSError, UnicodeDecodeError):
            paths.append(plainfile.read_text(marker, encoding="utf-8"))
        marker.unlink(missing_ok=True)
    return paths


def _others_at_work(memory: Memory, session: str | None) -> dict[str, float]:
    """The last event of each checkout where another session is at work. Drops old markers."""
    mine = f"{_key(session)}-" if session else None
    limit = time.time() - WORKING_SECONDS
    found: dict[str, float] = {}
    for marker in plainfile.files_in(memory.dir, _folder(memory)):
        seen_at = marker.stat().st_mtime
        if seen_at < limit:
            marker.unlink(missing_ok=True)
        elif not (mine and marker.name.startswith(mine)):
            path = plainfile.read_text(marker, encoding="utf-8")
            found[path] = max(seen_at, found.get(path, 0.0))
    return found


def _sharers(memory: Memory, session: str) -> list[str]:
    """Where other work had a hook event in the last WORKING_SECONDS: another session anywhere,
    or a helper of this session in another checkout, because helpers share their parent's key."""
    mine = f"{_key(session)}-{_key(str(memory.project.root))}"
    limit = time.time() - WORKING_SECONDS
    found = set()
    for marker in plainfile.files_in(memory.dir, _folder(memory)):
        with contextlib.suppress(OSError, UnicodeDecodeError):  # a stop removes markers at once
            if marker.name != mine and marker.stat().st_mtime >= limit:
                found.add(_place(memory, plainfile.read_text(marker, encoding="utf-8")))
    return sorted(found)


def _command_words(part: str) -> list[str]:
    """The words of one step from its command on: past `(` and `$(`, settings (also `x=$(`),
    `sudo` and `env` with their options, and with no `)` at the end. A `bash -c` script and a
    git alias stay out: the parser reads no script and no git config."""
    words = [word for word in _core_words(_words(part.strip())) if word]
    run_as = False
    while words:
        word = words[0]
        if SETTING.fullmatch(word) and "$(" in word:
            words[0] = word.split("$(", 1)[1]
        elif word.startswith(("(", "$(")):
            words[0] = word.lstrip("$(")
        elif SETTING.fullmatch(word) or word in RUN_AS or (run_as and word.startswith("-")):
            run_as = run_as or word in RUN_AS
            words.pop(0)
        else:
            break
        if words and not words[0]:
            words.pop(0)
    if words:
        words[-1] = words[-1].rstrip(")")
    return [word for word in words if word]


def _stash_args(words: list[str]) -> list[str] | None:
    """The words after `stash` in a `git stash` step, or None for another command."""
    if not words or PurePath(words[0]).name != "git":
        return None
    index = 1
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in GIT_VALUE_OPTIONS else 1
    return words[index + 1 :] if words[index : index + 1] == ["stash"] else None


def takes_shared_stash(command: str) -> bool:
    """True when a step can take or lose an entry of another checkout: `clear`, a `pop`, `apply`,
    `drop` or `branch` of the top entry, or a push with no message, which a bare pop takes."""
    for part, _ in _parts(command):
        args = _stash_args(_command_words(part))
        if args is None:
            continue
        sub = args[0] if args and not args[0].startswith("-") else "push"
        named = [arg for arg in args[1:] if not arg.startswith("-")]
        message = any(arg.startswith(("-m", "--message")) for arg in args)
        if (
            sub == "clear"
            or (sub in ("pop", "apply", "drop") and not named)
            or (sub == "branch" and len(named) < 2)
            or (sub in ("push", "save") and not message and not (sub == "save" and named))
        ):
            return True
    return False


def stash_note(memory: Memory, session: str, command: str) -> str | None:
    """A warning, once in a session, when this command uses the stash list that live work shares."""
    if not takes_shared_stash(command):
        return None
    places = _sharers(memory, session)
    if not places or not take_once(memory, session, "stash", ["stash"]):
        return None
    more = f" and {len(places) - MAX_LINES} more" if len(places) > MAX_LINES else ""
    shown = ", ".join(places[:MAX_LINES]) + more
    return (
        "memory: all checkouts of this repo share one git stash list, and other work is live in "
        f"{shown}. A `pop`, `apply`, `drop` or `clear` of the top entry can take or lose an entry "
        "of that work, and a bare pop there can take an entry with no name. Make sure that each "
        "entry that you use is yours (`git stash list`). To put work aside, commit it on a branch, "
        "or run `git stash push -m NAME`, then `git stash apply stash@{n}` for the entry with that "
        "name."
    )


def _read_status(path: Path) -> tuple[str | None, list[str]] | None:
    """The branch and the changed paths. No optional lock, because another session works here."""
    args = ("status", "--porcelain", "-z", "--branch", "--no-renames", "--untracked-files=normal")
    out = run_git(path, "--no-optional-locks", *args, timeout=GIT_TIMEOUT, env=tree_env())
    if out is None:
        return None
    head, *rows = out.split("\0")
    branch = head.removeprefix("## ").removeprefix("No commits yet on ").split("...")[0]
    return (None if branch.startswith("HEAD ") else branch), [row[3:] for row in rows if row]


def _holds_a_checkout(path: Path, entry: str, checkouts: list[Path]) -> bool:
    """A worktree inside this checkout shows as an untracked folder. It is no change here."""
    full = path / entry.rstrip("/")
    return any(c != path and (c == full or full in c.parents) for c in checkouts)


def _read_checkouts(memory: Memory, at_work: dict[str, float], here_counts: bool, skip: set[Path]):
    """The checkouts with live work, and how many could not be read. A helper line holds `skip`."""
    project = memory.project
    root = project.root
    wanted = [
        path
        for path in project.checkouts
        if (path != root or here_counts) and path.resolve() not in skip
    ]
    wanted.sort(key=lambda path: (path != root, str(path) not in at_work))
    found = []
    unread = max(len(wanted) - MAX_CHECKOUTS, 0)
    for path in wanted[:MAX_CHECKOUTS]:
        cuts = deadline.git_cuts()
        status = _read_status(path)
        if status is None:
            unread += deadline.git_cuts() > cuts
            continue
        branch, files = _work_in(memory, path, status)
        seen_at = at_work.get(str(path))
        if files or seen_at:
            found.append(Checkout(path, branch, files, seen_at))
    return found, unread


def _work_in(memory: Memory, path: Path, status: tuple[str | None, list[str]]):
    """The branch and the changed files that count, from a status of the checkout at `path`."""
    branch, entries = status
    files = [
        entry
        for entry in entries
        if not is_junk_path(entry)
        and not is_memory_path(entry, path, memory.dir)
        and not _holds_a_checkout(path, entry, memory.project.checkouts)
    ]
    return branch, files


def _ago(at: float) -> str:
    minutes = max(int((time.time() - at) // 60), 1)
    if minutes < 120:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h" if hours < 48 else f"{hours // 24}d"


def _place(memory: Memory, path: str) -> str:
    root = memory.project.root.resolve()
    if not path or Path(path).resolve() == root:
        return "this checkout"
    return name(os.path.relpath(Path(path).resolve(), root))


def _helper_work(memory: Memory, helper: helpers.Helper) -> tuple[str, str, bool]:
    """The branch of the helper's checkout, what that checkout holds now, and False when it
    holds no commit since the start and no uncommitted change."""
    path = Path(helper.checkout or "")
    status = _read_status(path)
    if status is None:
        return "", "its checkout could not be read in time", True
    branch, files = _work_in(memory, path, status)
    commits = 0
    if helper.base:
        count = run_git(path, "rev-list", "--count", f"{helper.base}..HEAD", timeout=GIT_TIMEOUT)
        commits = int(count) if count and count.strip().isdigit() else 0
    parts = []
    if commits:
        parts.append(f"{commits} commit(s) since it started")
    if files:
        shown = ", ".join(name(entry) for entry in files[:MAX_FILES])
        more = len(files) - MAX_FILES
        parts.append(f"uncommitted {shown}" + (f" and {more} more" if more > 0 else ""))
    held = ", ".join(parts) or "no uncommitted change and no commit there"
    return (f", branch {name(branch)}" if branch else ""), held, bool(parts)


# Only an end that the hooks saw ends a record. A missed one is no proof that the helper runs.
# Claude Code fires SubagentStop for a helper that TaskStop stops only when the stop cuts its
# stream. When the stream ends first, no hook runs, so a missed end can be a stop.
NO_END = "no end recorded, so it may have been stopped or ended unseen"
RUNNING = "started by this session; it may still be running, or it was stopped or ended unseen"


def _named_helpers(
    memory: Memory, records: list[helpers.Helper]
) -> tuple[list[helpers.Helper], dict[str, tuple[str, str, bool]], int]:
    """The records that the load names, the work in the checkout of each, and how many more.

    No hook event ends a lost record. Past helpers.SHOWN_SECONDS, a record is named only while
    its own checkout holds commits since it started or uncommitted changes, because that is live
    work; else it is noise. The work is read once, for the line too, and only until MAX_HELPERS
    are named, so a pile of old records costs no more git than the lines do.
    """
    since = time.time() - helpers.SHOWN_SECONDS
    named, work, more = [], {}, 0
    for helper in records:
        inside = helper.launched and helpers.is_checkout(memory.project, helper.checkout)
        old = helper.started_at < since
        if old and not inside:
            continue
        if len(named) >= MAX_HELPERS:
            more += 1
            continue
        if inside:
            work[helper.call] = _helper_work(memory, helper)
            if old and not work[helper.call][2]:
                continue
        named.append(helper)
    return named, work, more


def _helper_line(
    memory: Memory,
    helper: helpers.Helper,
    work: tuple[str, str, bool] | None,
    running: bool = False,
) -> str:
    """One line. `work` is what `_helper_work` read, for a helper in a checkout of the project."""
    about = '"' + helper.about.replace('"', "'") + '"'
    kind = f" ({name(helper.kind)})" if helper.kind else ""
    ago = _ago(helper.started_at)
    end = RUNNING if running else NO_END
    if not helper.launched:
        head = f"{about}{kind}, called {ago} ago in {_place(memory, helper.parent)}"
        state = ["not started, no end recorded"]
    elif work:
        branch, held, _ = work
        head = f"{about}{kind}, started {ago} ago in {_place(memory, helper.checkout)}{branch}"
        state = [end, held]
    elif helper.checkout:
        head = f"{about}{kind}, started {ago} ago in {_place(memory, helper.checkout)}"
        gone = (
            "that folder is no checkout of this project"
            if helper.has_checkout
            else "that checkout is gone now"
        )
        state = [end, gone]
    else:
        head = f"{about}{kind}, started {ago} ago in {_place(memory, helper.parent)}"
        state = [end]
    task = [f"task: {helper.task}"] if helper.task else []
    return mask(clean(f"- [helper] {head}: {'; '.join([*task, *state])}."), memory.env)


def _branch_note(memory: Memory, branch: str | None) -> str | None:
    if not branch:
        return None
    notes = [
        state
        for state in memory.states.values()
        if state.get("scope") == "short"
        and state.get("until_branch_merged") == branch
        and effective_status(state)[0] == "active"
    ]
    if notes:
        return load_text(max(notes, key=lambda state: state.get("learned_at") or ""))
    head = note_head(memory.dir / "branches" / f"{branch}.md")
    return head[0] if head else None


def _line(memory: Memory, checkout: Checkout) -> str:
    root = memory.project.root
    place = "this checkout" if checkout.path == root else os.path.relpath(checkout.path, root)
    parts = []
    if checkout.seen_at:
        minutes = max(int((time.time() - checkout.seen_at) // 60), 1)
        parts.append(f"a session worked here {minutes}m ago")
    if checkout.files:
        shown = ", ".join(name(entry) for entry in checkout.files[:MAX_FILES])
        more = len(checkout.files) - MAX_FILES
        parts.append(f"uncommitted {shown}" + (f" and {more} more" if more > 0 else ""))
    note = _branch_note(memory, checkout.branch)
    if note:
        parts.append(f"note: {' '.join(note.split()[:NOTE_WORDS])}")
    branch = f", branch {name(checkout.branch)}" if checkout.branch else ""
    return mask(clean(f"- [live] {name(place)}{branch}: {'; '.join(parts)}."), memory.env)


def add_lines(
    memory: Memory,
    lines: list[str],
    session: str | None,
    hide_helpers_of: str | None = None,
    own_helpers_of: str | None = None,
) -> list[str]:
    """The load with its live work added, or as it was when there is none.

    With no session, a plain `memory load` cannot tell its own changes and marker from another's,
    so it says nothing of its own checkout. A session names its own checkout only when another
    session is at work here. Old changes here with no session at work are most often the owner's,
    and the order not to commit them would get in the way of a plain request to commit.
    The helpers of `hide_helpers_of` are the siblings of a helper's own load, so they are not named.
    The helpers of `own_helpers_of` can still run in this process (a compaction), so they come
    first, say so, and are not marked as told: a told record ends at the next stop.
    """
    if FRAME_HEADER not in lines:
        return lines
    records = helpers.shown(memory, hide_helpers_of)
    records.sort(key=lambda helper: helper.session != own_helpers_of)
    named: list[helpers.Helper] = []
    body: list[str] = []
    found: list[Checkout] = []
    unread = 0
    with deadline.within(BUDGET):
        named, work, more = _named_helpers(memory, records)
        body = [
            _helper_line(memory, h, work.get(h.call), h.session == own_helpers_of) for h in named
        ]
        if more:
            body.append(f"- [helper] {more} more helper(s) with no end.")
        if memory.project.is_git:
            at_work = _others_at_work(memory, session)
            here = session is not None and str(memory.project.root) in at_work
            skip = {Path(h.checkout or "").resolve() for h in named if h.has_checkout}
            found, unread = _read_checkouts(memory, at_work, here, skip)
    if session is not None:
        told = [helper.call for helper in named if helper.session != own_helpers_of]
        helpers.note_told(memory, told, session)
    body += [_line(memory, checkout) for checkout in found[:MAX_LINES]]
    held = len(found) - MAX_LINES
    if held > 0:
        body.append(f"- [live] {held} more checkout(s) hold live work.")
    if unread:
        body.append(f"- [live] {unread} more checkout(s) not read, so this list can miss work.")
    if not body:
        return lines
    frame = lines.index(FRAME_HEADER)
    return [*lines[:frame], ORDER, FRAME_HEADER, "## Live work", *body, *lines[frame + 1 :]]
