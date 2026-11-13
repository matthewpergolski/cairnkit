"""Why each helper of a session started, from the call until an event ends it.

A Ctrl+C ends the process in a turn, so no stop runs. So the record comes from the hooks that run
before and while a helper starts. Claude Code's `PreToolUse` on the `Agent` tool (`Task` before)
holds the description and the prompt. `SubagentStart` holds the helper's id and its checkout, but
no brief. A background call returns at once with the id (`async_launched`), and the records join
on it. A foreground call returns only at its end, so `SubagentStart` takes the oldest call of the
session for that agent type that has no helper yet. Calls in one message start in the order sent.

An event ends a record, not the time since its call:

- `SubagentStop` of its helper, or the result of its call (a foreground helper that returned, or
  a failure);
- the stop of its own turn, for a call that never launched a helper;
- the stop of a session whose load named it, unless the helper's own checkout is still there.
  That checkout holds the evidence, so the record stays with it. A gone checkout is no end by
  itself: on a Ctrl+C, Claude Code removes the worktree of a killed helper that changed nothing.

TaskStop does not always fire SubagentStop, so a stopped helper can leave its record. Claude Code
writes each step of a helper to the helper's own transcript, `<parent transcript without
.jsonl>/subagents/agent-<agent_id>.jsonl`, so a transcript with no write for QUIET_SECONDS is an
end too. A load only reads the file time, never the file. A record with no such file (another
agent, or a transcript not written yet) has no such end.

A load names a record for SHOWN_SECONDS after the call. After that, it names the record only while
the record's own checkout holds commits since the start that no main branch holds, or uncommitted
changes (live.py), because that is live work. Else the record is noise.

All records live in one file under one lock, because helpers of one session start at once.
The text is agent-written: each field is masked and cut before it is stored.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from cairnkit import deadline, plainfile
from cairnkit.memory import Memory
from cairnkit.paths import Project, run_git
from cairnkit.secretscan import mask
from cairnkit.selection import clean
from cairnkit.store import LockBusy, locked

AGENT_TOOLS = frozenset({"Agent", "Task"})
ABOUT_WORDS = 12
# A real Haiku brief put its one value at word 41, after a preamble and a first step.
TASK_WORDS = 60
# A session cannot start more at once. Past this, the oldest record goes, so the file stays small.
MAX_RECORDS = 50
GIT_TIMEOUT = 1.0
# A record may wait this long for another hook's write. A load must not wait longer.
LOCK_WAIT = 0.5
# No hook event comes from a helper record after its start, so a lost end stays. A load names it
# for a day, longer than a helper runs, and then only while its checkout holds the work it left.
SHOWN_SECONDS = 24 * 3600
# A helper writes its transcript at each step. One Bash call ends in 10 minutes at most.
QUIET_SECONDS = 1800


@dataclass(frozen=True)
class Helper:
    call: str  # the tool_use_id of the call, or the helper id when no call was heard
    session: str  # the parent's session key
    kind: str  # the agent type
    about: str  # the description: masked, one line, at most ABOUT_WORDS words
    task: str  # the start of the prompt: masked, one line, at most TASK_WORDS words
    started_at: float  # the real clock at the call
    parent: str = ""  # the parent's checkout at the call
    agent: str | None = None  # the helper id, once known
    checkout: str | None = None  # the helper's own checkout, when it is not the parent's
    base: str | None = None  # HEAD of that checkout when the helper started
    told: tuple[str, ...] = field(default_factory=tuple)  # sessions whose load named it
    transcript: str | None = None  # the helper's own transcript, on Claude Code

    @property
    def quiet(self) -> bool:
        """True when its own transcript is there and had no write for QUIET_SECONDS."""
        if not self.transcript:
            return False
        try:
            return os.stat(self.transcript).st_mtime < time.time() - QUIET_SECONDS
        except (OSError, ValueError):
            return False

    @property
    def launched(self) -> bool:
        return self.agent is not None

    @property
    def has_checkout(self) -> bool:
        return bool(self.checkout) and os.path.isdir(self.checkout or "")


def is_checkout(project: Project, path: str | None) -> bool:
    """True when path is one of this project's checkouts, the only folders where git runs.

    A record or a payload can name any folder, and a folder can hold a git config that runs a
    command. `git worktree list` names the project's own checkouts.
    """
    if not path:
        return False
    real = Path(path).resolve()
    return any(real == checkout.resolve() for checkout in project.checkouts)


def _folder(memory: Memory) -> Path:
    return memory.dir / ".sessions" / "helpers"


def _file(memory: Memory) -> Path:
    return _folder(memory) / "open.json"


def _read(memory: Memory) -> list[Helper]:
    try:
        rows = json.loads(plainfile.read_text(_file(memory), encoding="utf-8"))
    except (OSError, ValueError):
        return []
    known = {item.name for item in fields(Helper)}
    found = []
    for row in rows if isinstance(rows, list) else []:
        with contextlib.suppress(TypeError, ValueError, AttributeError):
            # A field of a later build is left out, so its records are still read.
            kept = {key: value for key, value in row.items() if key in known}
            found.append(Helper(**{**kept, "told": tuple(row.get("told") or ())}))
    return found


def _write(memory: Memory, helpers: list[Helper]) -> None:
    path = plainfile.inside(memory.dir, _file(memory))
    for old in plainfile.files_in(memory.dir, path.parent, ".open-*.tmp"):  # a killed write
        with contextlib.suppress(OSError):
            if old.stat().st_mtime < time.time() - 3600:
                old.unlink()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".open-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps([asdict(h) for h in helpers[-MAX_RECORDS:]]))
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _update(memory: Memory, change: Callable[[list[Helper]], list[Helper]]) -> None:
    """Apply `change` to the records under the lock. A lock held past LOCK_WAIT skips it."""
    plainfile.inside(memory.dir, _folder(memory)).mkdir(parents=True, exist_ok=True)
    with (
        contextlib.suppress(LockBusy),
        deadline.within(LOCK_WAIT),
        locked(_folder(memory) / ".lock", root=memory.dir),
    ):
        helpers = _read(memory)
        changed = change(helpers)
        if changed != helpers:
            _write(memory, changed)


def _words(text: str, limit: int, memory: Memory) -> str:
    """One line of at most `limit` words, masked. Masked first, so a cut cannot split a secret."""
    words = clean(mask(text, memory.env)).split()
    return " ".join(words[:limit]) + (" ..." if len(words) > limit else "")


def _same(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return Path(a).resolve() == Path(b).resolve()


def on_call(memory: Memory, session: str, payload: dict) -> None:
    """`PreToolUse` on the Agent tool: the purpose, before the helper starts."""
    if payload.get("tool_name") not in AGENT_TOOLS:
        return
    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    # A prompt often opens with a line such as "Do these steps in order:", so all lines count.
    prompt = str(tool_input.get("prompt") or "")
    description = str(tool_input.get("description") or "")
    record = Helper(
        call=str(payload.get("tool_use_id") or f"call-{time.time_ns()}"),
        session=session,
        kind=str(tool_input.get("subagent_type") or ""),
        about=_words(description or prompt, ABOUT_WORDS, memory),
        task=_words(prompt, TASK_WORDS, memory) if description else "",
        started_at=time.time(),
        parent=str(payload.get("cwd") or memory.project.root),
    )
    _update(memory, lambda helpers: [h for h in helpers if h.call != record.call] + [record])


def on_result(memory: Memory, payload: dict) -> None:
    """`PostToolUse` or `PostToolUseFailure` on the Agent tool. Only a background launch goes on."""
    if payload.get("tool_name") not in AGENT_TOOLS or not payload.get("tool_use_id"):
        return
    call = str(payload["tool_use_id"])
    response = payload.get("tool_response")
    response = response if isinstance(response, dict) else {}
    launched = response.get("status") == "async_launched" and response.get("agentId")
    failed = "Failure" in str(payload.get("hook_event_name") or "")
    if launched and not failed:
        agent = str(response["agentId"])
        _update(
            memory,
            lambda helpers: [replace(h, agent=agent) if h.call == call else h for h in helpers],
        )
    else:
        _update(memory, lambda helpers: [h for h in helpers if h.call != call])


def _own_transcript(payload: dict, agent: str) -> str | None:
    """Where Claude Code writes the helper's transcript, from the parent's `transcript_path`.

    `agent_transcript_path` counts only in the folder of the parent's transcript, where Claude
    Code writes it. A load reads the time of that file, so no payload can point it elsewhere.
    """
    parent = os.path.expanduser(str(payload.get("transcript_path") or ""))
    if not parent.endswith(".jsonl"):
        return None
    named = str(payload.get("agent_transcript_path") or "")
    own = Path(os.path.normpath(os.path.expanduser(named))) if named else None
    if own and Path(os.path.normpath(parent)).parent in own.parents:
        return str(own)
    name = agent.removeprefix("agent-")  # Claude Code ids carry no prefix; never write it twice
    return str(Path(parent).with_suffix("") / "subagents" / f"agent-{name}.jsonl")


def on_start(memory: Memory, session: str, payload: dict) -> None:
    """`SubagentStart`: the helper's id and its own checkout."""
    agent = str(payload.get("agent_id") or "")
    if not agent:
        return
    cwd = str(payload.get("cwd") or "")
    kind = str(payload.get("agent_type") or "")

    def join(helpers: list[Helper]) -> list[Helper]:
        mine = next((h for h in helpers if h.agent == agent), None)
        if mine is None:
            waiting = [
                h
                for h in helpers
                if h.session == session and not h.launched and h.kind in ("", kind)
            ]
            mine = min(waiting, key=lambda h: h.started_at, default=None)
        if mine is None or mine.checkout:
            return helpers
        here = cwd and not _same(cwd, mine.parent) and is_checkout(memory.project, cwd)
        own = cwd if here else None
        base = run_git(Path(own), "rev-parse", "HEAD", timeout=GIT_TIMEOUT) if own else None
        transcript = _own_transcript(payload, agent)
        found = replace(mine, agent=agent, checkout=own, base=base or None, transcript=transcript)
        return [found if h.call == mine.call else h for h in helpers]

    _update(memory, join)


def on_end(memory: Memory, payload: dict) -> None:
    """`SubagentStop`: that helper ended."""
    agent = str(payload.get("agent_id") or "")
    if agent:
        _update(memory, lambda helpers: [h for h in helpers if h.agent != agent])


def on_main_stop(memory: Memory, session: str) -> None:
    """The stop of a turn: its calls that launched nothing, and what its load named.

    A background helper outlives the turn, and its launch gave it an id, so it stays.
    """

    def ends(h: Helper) -> bool:
        never_started = h.session == session and not h.launched
        return never_started or (session in h.told and not h.has_checkout)

    _update(memory, lambda helpers: [h for h in helpers if not ends(h)])


def shown(memory: Memory, hide_session: str | None) -> list[Helper]:
    """The records that a load can name, oldest first. live.py drops the old ones with no work.

    `hide_session` is the session of a helper's own load, whose siblings can still run.
    """
    return [h for h in _read(memory) if h.session != hide_session]


def note_told(memory: Memory, calls: list[str], session: str) -> None:
    """The load of `session` named these records."""

    def tell(h: Helper) -> Helper:
        return (
            replace(h, told=(*h.told, session)) if h.call in calls and session not in h.told else h
        )

    if calls:
        _update(memory, lambda helpers: [tell(h) for h in helpers])
