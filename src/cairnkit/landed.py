"""Work that landed: git, not the clock, says that the work of a one-time approval is done.

Only a rule or a decision that reads as a yes to one piece of work (`one_work`), and that names
that work in `files`, can land. A lasting policy never lands, also when it names a file that
changes each week, and a path in the text of a fact is never read as its work.

The work landed when a landing branch has a commit that changed each path in `files` after the
fact was written or last changed. A landing branch is the default branch, `dev` or `develop`,
local or on `origin`, read along first parents, so a merge counts on the day it merged. A commit
that deletes a path counts. A rename does not: it moves the file and does not do the work, and
the new path is not followed. A folder in `files` never lands, because git names the files in it,
not the folder. A root commit, and the graft root of a shallow clone, show each file as new, so
they count for no path.

The first commit of work in progress counts too: git cannot tell a first step from the last. So
nothing here ends a fact. `memory tidy` proposes the end, and the agent decides. A change to the
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
from cairnkit.paths import INTEGRATION_BRANCHES, default_branch, run_git

CACHE_NAME = ".landed.json"
# Paths for one `git log`. Past this, the oldest facts wait for a later read.
MAX_PATHS = 400
GIT_TIMEOUT = 2.0
AUTO_WRITERS = ("auto-tidy",)
# A rule or a decision about one piece of work can end when that work lands.
ENDS_WITH_WORK = ("rule", "decision")
# Python strips the separators U+001C to U+001F as white space, so these are NUL and SOH.
_COMMIT = "\x00"
_FIELD = "\x01"
# An approval is a yes with its object of work right after it. A phrase that ends in a
# preposition ("yes to", "go ahead with", "LGTM on") takes any object. A bare verb takes one only
# after a determiner or a word of work: "approved the parser", not "approved licenses" or
# "approved by the owner". "approve" alone is out: "ask the owner to approve each deploy" is a
# lasting policy. A number such as "#123" or "migration 0001" is no approval: "never edit
# migration 0001" names one piece of work and holds for ever.
_OBJECT = (
    r"(?:(?:the|this|that|these|those|a|an|our|my|your|their|its)\s+\S"
    r"|(?:pr|pull\s+request|migration|spec|plan|change|refactor|rewrite|move|merge|release)\b)"
)
_APPROVAL = re.compile(
    r"(?i)(?:(?:\byes,?\s+to|\bgo\s+ahead\s+(?:with|on)|\bsigned\s+off\s+on"
    r"|\blgtm\s+(?:on|for|to)|\bgreen[-\s]+light(?:ed)?\s+(?:for|on|to))\s+\w"
    r"|(?:\bapprov(?:ed|es)|\bok(?:ay)?(?:'|\u2019)?e?d|\bgreen[-\s]+light(?:ed)?)"
    rf"\s+{_OBJECT})"
)
_SCOPE = re.compile(r"(?i)\bfor\s+this\s+(?:release|sprint|branch|pr)\b")
# A policy: it opens with a word of always or never, or a negation stands right before the yes.
_POLICY = re.compile(r"(?i)^\W*(?:only|never|always|do\s+not|don't|dont|no|every|each|any)\b")
_NEGATED = re.compile(r"(?i)(?:\bnot|\bnever|n't|\bno)\s+(?:\w+\s+)?$")


def one_work(text: str) -> bool:
    """True when the text reads as approval of one piece of work, not as a lasting policy."""
    text = str(text)
    if _POLICY.search(text):
        return False
    if _SCOPE.search(text):
        return True
    return any(not _NEGATED.search(text[: m.start()]) for m in _APPROVAL.finditer(text))


def work_files(state: dict) -> tuple[str, ...]:
    """The paths whose commits can land this fact. Empty for a fact that can never land."""
    if state.get("kind") not in ENDS_WITH_WORK or not one_work(str(state.get("text", ""))):
        return ()
    return tuple(sorted({str(f).strip().strip("/") for f in state.get("files") or []} - {""}))


@dataclass(frozen=True)
class Landed:
    """The commit on the main branch that completed the work of a fact."""

    commit: str
    date: str
    subject: str


@dataclass(frozen=True)
class _Want:
    """What one fact needs: a commit on each path, after `since`."""

    id: str
    since: str
    paths: tuple[str, ...]

    @property
    def key(self) -> str:
        return "|".join([self.id, self.since, ",".join(self.paths)])


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
    """The active facts that can land, newest first, up to MAX_PATHS paths in all."""
    found = []
    for state in memory.states.values():
        if state.get("status") != "active" or state.get("pinned"):
            continue
        since, paths = _since(state), work_files(state)
        if since and paths:
            found.append(_Want(state["id"], since, paths))
    found.sort(key=lambda want: (parse_time(want.since), want.id), reverse=True)
    kept, used = [], 0
    for want in found:
        if used + len(want.paths) > MAX_PATHS:
            break
        kept.append(want)
        used += len(want.paths)
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

    No pathspec: with one, git cannot see that a path moved, and shows a rename as a delete.
    None when git did not answer, which is not "no commit".
    """
    out = run_git(
        root,
        "-c",
        "log.showRoot=false",
        "-c",
        "core.quotePath=false",
        "log",
        "--first-parent",
        "-m",
        "-M",
        "--name-status",
        f"--since={since}",
        "--format=%x00%h%x01%ct%x01%cs%x01%s",
        *[line.split(" ", 1)[1] for line in refs],
        "--",
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
        for line in filter(None, names.splitlines()):
            # "M\tpath", "D\tpath", or "R100\told\tnew": a rename changes only the new path.
            path = line.split("\t")[-1]
            if path in paths and (path not in newest or newest[path][0] < when):
                newest[path] = (when, evidence)
    return newest


def _decide(want: _Want, newest: dict[str, tuple]) -> Landed | None:
    after = parse_time(want.since).timestamp()
    done = [newest[p] for p in want.paths if newest.get(p, (0,))[0] > after]
    if len(done) < len(want.paths):
        return None
    return max(done, key=lambda pair: pair[0])[1]


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
        paths = {p for want in wants for p in want.paths}
        newest = _newest(root, refs, paths, oldest)
        if newest is None:
            return {}
        facts = {}
        for want in wants:
            evidence = _decide(want, newest)
            facts[want.key] = list(astuple(evidence)) if evidence else None
        _write_cache(memory, refs, facts)
    return {want.id: Landed(*facts[want.key]) for want in wants if facts.get(want.key) is not None}


STALE_NAMED = 5


def stale_rules(memory: Memory, rules: list[dict]) -> list[str]:
    """The rules most likely stale: work that landed first, then the oldest yes to one piece of
    work. A lasting policy is not named."""
    done = find(memory)
    gone = sorted(
        (r for r in rules if r["id"] in done), key=lambda r: (done[r["id"]].date, r["id"])
    )
    yes = sorted(
        (r for r in rules if r["id"] not in done and one_work(str(r.get("text", "")))),
        key=lambda r: (r.get("learned_at") or "", r["id"]),
    )
    return [r["id"] for r in (*gone, *yes)]


def stale_line(memory: Memory, rules: list[dict]) -> str | None:
    """One line for a load or a check whose rules are over their budget. Ids only."""
    ids = stale_rules(memory, rules)
    if not ids:
        return None
    more = f" and {len(ids) - STALE_NAMED} more" if len(ids) > STALE_NAMED else ""
    return (
        f"Rules most likely stale (work landed, then old one-time approvals): "
        f"{', '.join(ids[:STALE_NAMED])}{more}. `memory tidy` shows the commits. End one that no "
        'longer holds: memory change ID --status expired --reason "...".'
    )
