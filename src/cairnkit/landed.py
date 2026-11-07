"""Work that landed: git, not the clock, says that the work a fact is about is done.

A fact names its work in `files`, or else by the repo paths in its text. The work landed when the
main branch has a commit on each of those paths after the fact was written or last changed. The
main branch is where work lands: the default branch, `dev` or `develop`, local or on `origin`,
read along first parents, so a merge counts on the day it merged. A commit that deletes a path
counts too. A text path that is not in this checkout and has no such commit is no repo path, and
it does not count. A fact that names no path never lands.

Nothing here ends a fact. `memory tidy` proposes the end, and the agent decides. A change to the
fact after the commit, such as `memory change ID --status active --reason "..."`, says that the
agent looked, so the same commit does not count again.

One `git log` reads all facts at once. The answer is kept in the memory folder until a landing
branch moves or a fact changes, so a hook reads it at the cost of one `git for-each-ref`.
"""

from __future__ import annotations

import contextlib
import json
import re
from dataclasses import astuple, dataclass

from cairnkit import plainfile
from cairnkit.clock import parse_time
from cairnkit.memory import Memory
from cairnkit.paths import INTEGRATION_BRANCHES, LINK_NAME, default_branch, run_git

CACHE_NAME = ".landed.json"
# Paths for one `git log`. Past this, the oldest facts wait for a later read.
MAX_PATHS = 400
GIT_TIMEOUT = 2.0
AUTO_WRITERS = ("auto-tidy",)
_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*")
_EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")
# Python strips the separators U+001C to U+001F as white space, so these are NUL and SOH.
_COMMIT = "\x00"
_FIELD = "\x01"
# The owner's yes to one piece of work, or a name of one piece of work. "approve" alone is out:
# "ask the owner to approve each deploy" is a lasting policy.
_ONE_WORK = re.compile(
    r"(?i)\byes,?\s+to\b|\bapproved\b|\bgo\s+ahead\s+with\b|\bsigned\s+off\s+on\b"
    r"|\bfor\s+this\s+(?:release|sprint|branch|pr)\b"
    r"|\b(?:migration|spec|pr)\s*#?\d+|(?<![\w&])#\d+\b"
)


def one_work(text: str) -> bool:
    """True when the text reads as approval of one piece of work, not as a lasting policy."""
    return bool(_ONE_WORK.search(text))


@dataclass(frozen=True)
class Landed:
    """The commit on the main branch that completed the work of a fact."""

    commit: str
    date: str
    subject: str


@dataclass(frozen=True)
class _Want:
    """What one fact needs: every `required` path, and `optional` paths only when they changed."""

    id: str
    since: str
    required: tuple[str, ...]
    optional: tuple[str, ...]

    @property
    def key(self) -> str:
        return "|".join([self.id, self.since, ",".join(self.required), ",".join(self.optional)])


def named_paths(state: dict, root) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(required, optional) paths. `files` are all required. A text path is required when it is
    in this checkout, and optional when it is not."""
    files = sorted({str(f).strip().strip("/") for f in state.get("files") or []} - {""})
    if files:
        return tuple(files), ()
    required, optional = set(), set()
    for token in _TOKEN.findall(str(state.get("text", ""))):
        token = token.rstrip("./-")
        parts = token.split("/")
        if not ("/" in token or _EXTENSION.search(token)) or ".." in parts:
            continue
        if parts[0] == LINK_NAME:
            continue
        (required if (root / token).exists() else optional).add(token)
    return tuple(sorted(required)), tuple(sorted(optional - required))


def _since(state: dict) -> str:
    """When the fact was written, or last changed by a person or an agent."""
    times = [str(state.get("learned_at") or "")]
    times += [
        str(change.get("at") or "")
        for change in state.get("history", [])
        if change.get("writer") not in AUTO_WRITERS
    ]
    known = []
    for value in times:
        with contextlib.suppress(ValueError, TypeError):
            known.append((parse_time(value), value))
    return max(known)[1] if known else ""


def _wants(memory: Memory) -> list[_Want]:
    """The active facts that name a path, newest first, up to MAX_PATHS paths in all."""
    root = memory.project.root
    found = []
    for state in memory.states.values():
        if state.get("status") != "active" or state.get("pinned"):
            continue
        since = _since(state)
        required, optional = named_paths(state, root)
        if since and (required or optional):
            found.append(_Want(state["id"], since, required, optional))
    found.sort(key=lambda want: (parse_time(want.since), want.id), reverse=True)
    kept, used = [], 0
    for want in found:
        cost = len(want.required) + len(want.optional)
        if used + cost > MAX_PATHS:
            break
        kept.append(want)
        used += cost
    return kept


def _landing_refs(root) -> list[str]:
    """`<commit> <ref>` for each ref where work lands, one ref for each commit."""
    base = default_branch(root)
    if not base:
        return []
    names = sorted({base, *INTEGRATION_BRANCHES})
    wanted = [f"refs/heads/{n}" for n in names] + [f"refs/remotes/origin/{n}" for n in names]
    out = run_git(root, "for-each-ref", "--format=%(objectname) %(refname)", *wanted) or ""
    by_commit = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
    return sorted(f"{commit} {ref}" for commit, ref in by_commit.items())


def _newest(root, refs: list[str], paths: set[str], since: str) -> dict[str, tuple] | None:
    """For each path, the newest commit after `since` that changed it: (time, Landed).

    None when git did not answer, which is not "no commit".
    """
    out = run_git(
        root,
        "--literal-pathspecs",
        "log",
        "--first-parent",
        "-m",
        "--no-renames",
        "--name-only",
        f"--since={since}",
        "--format=%x00%h%x01%ct%x01%cs%x01%s",
        *[line.split(" ", 1)[1] for line in refs],
        "--",
        *sorted(paths),
        timeout=GIT_TIMEOUT,
    )
    if out is None:
        return None
    newest: dict[str, tuple] = {}
    for block in out.split(_COMMIT)[1:]:
        head, _, names = block.partition("\n")
        fields = head.split(_FIELD)
        if len(fields) != 4 or not fields[1].isdigit():
            continue
        when, evidence = int(fields[1]), Landed(fields[0], fields[2], fields[3])
        for name in filter(None, names.splitlines()):
            parts = name.split("/")
            for path in {"/".join(parts[:n]) for n in range(1, len(parts) + 1)} & paths:
                if path not in newest or newest[path][0] < when:
                    newest[path] = (when, evidence)
    return newest


def _decide(want: _Want, newest: dict[str, tuple]) -> Landed | None:
    after = parse_time(want.since).timestamp()
    done = {
        p: newest[p] for p in (*want.required, *want.optional) if newest.get(p, (0,))[0] > after
    }
    if not done or any(path not in done for path in want.required):
        return None
    return max(done.values(), key=lambda pair: pair[0])[1]


def _read_cache(memory: Memory) -> dict:
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(plainfile.read_text(memory.dir / CACHE_NAME, encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("facts"), dict):
            return data
    return {}


def _write_cache(memory: Memory, tips: list[str], facts: dict) -> None:
    with contextlib.suppress(OSError):
        path = plainfile.inside(memory.dir, memory.dir / CACHE_NAME)
        plainfile.write_text(path, json.dumps({"tips": tips, "facts": facts}), encoding="utf-8")


def find(memory: Memory) -> dict[str, Landed]:
    """Fact id to the commit that landed its work, for each active fact whose work landed."""
    root = memory.project.root
    wants = _wants(memory)
    if not wants or not memory.project.is_git:
        return {}
    refs = _landing_refs(root)
    if not refs:
        return {}
    cache = _read_cache(memory)
    facts = cache.get("facts", {})
    if cache.get("tips") != refs or any(want.key not in facts for want in wants):
        oldest = min((want.since for want in wants), key=parse_time)
        paths = {p for want in wants for p in (*want.required, *want.optional)}
        newest = _newest(root, refs, paths, oldest)
        if newest is None:
            return {}
        facts = {}
        for want in wants:
            evidence = _decide(want, newest)
            facts[want.key] = list(astuple(evidence)) if evidence else None
        _write_cache(memory, refs, facts)
    return {want.id: Landed(*facts[want.key]) for want in wants if facts.get(want.key) is not None}
