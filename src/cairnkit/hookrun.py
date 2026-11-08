"""`memory hook EVENT --agent NAME`: the command that agent hooks call.

Each agent tool reads hook output in its own format. This module keeps the
logic generic and only formats the output per agent. It never blocks a
session start, and it never crashes a stop: on an unexpected error it
prints the neutral output and exits 0.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import signal
import sys

from cairnkit import (
    adapters,
    autotidy,
    beforeshell,
    branchgate,
    deadline,
    followups,
    forgery,
    githook,
    helpers,
    hooks_cmd,
    instruction_files,
    legacy,
    live,
    loopbreak,
    native,
    owner_evidence,
    plainfile,
    signals,
    skills,
    tidy,
    usage,
)
from cairnkit.check import Health, read_health
from cairnkit.discover import ADD_LINE, CAPTURE_GUIDE, RULES_SHORT
from cairnkit.init import ensure_all_linked, ensure_linked, run_init
from cairnkit.load import run_load, take_notices
from cairnkit.memory import Memory, listed
from cairnkit.paths import (
    LINK_NAME,
    PATH_FILE,
    LostMemory,
    Project,
    lost_memory,
    lost_note,
    resolve_memory_dir,
    run_git,
    unverified_pointers,
)
from cairnkit.selection import AGENT_RULES, FRAME_FOOTER, FRAME_HEADER, clean
from cairnkit.session import (
    capture_reasons,
    hold_heard,
    hold_load,
    load_state,
    mark_loaded,
    note_helpers,
    start_session,
    take_heard,
    take_load,
)

NOTE_IDS = 10
STOP_SEEN = ".stop-problems.json"
STDIN_WAIT = 1
# Of the total session budget. The optional steps stop first, so the load keeps this much.
LOAD_RESERVE = 3.0
SUBAGENT_BUDGET = 300
# Agents that need a JSON empty object when memory exists but there is nothing to say.
JSON_NEUTRAL = frozenset({"codex", "cursor"})
# A generated adapter reads plain text on stdout.
TEXT_AGENTS = frozenset({"pi", "opencode"})
# Claude Code saves hook text over 10,000 characters to a file, and the model sees only 2,000 of it.
HOOK_TEXT_LIMIT = 9_000
# A load for these sources continues the session, so its events stay.
SAME_SESSION = frozenset({"compact", "resume", "reload"})
# A load for these sources runs in the same process, where a helper of the session can still run.
SAME_PROCESS = frozenset({"compact", "reload"})
# These tools add no text from a prompt hook, so what it would say waits for a later event.
DROPS_PROMPT_OUTPUT = frozenset({"grok", "cursor", "opencode"})
# Each other tool has a later prompt or tool hook that adds text with no turn. No stop can do that.
ONLY_STOP = frozenset({"generic"})
# Its hook docs (read 2026-11-01) call Stop passive, and no real run has shown otherwise.
STOP_MAY_BE_DROPPED = frozenset({"grok"})


def has_memory(project: Project, flag: str | None) -> bool:
    """True only when `memory init` has created a facts folder. Never creates paths.

    A link file that cannot be read means no memory for this hook, not a crash in the agent.
    """
    try:
        memdir, _ = resolve_memory_dir(project, flag)
    except (OSError, ValueError):
        return False
    return (memdir / "facts").is_dir()


def read_payload() -> dict:
    raw = ""
    try:
        with _time_budget(STDIN_WAIT):  # a tool writes this at once, then closes it
            raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def session_key(payload: dict) -> str:
    return str(payload.get("session_id") or payload.get("conversation_id") or "default")


def _names(items) -> str:
    names = ", ".join(item.id for item in items[:NOTE_IDS])
    return names + (f" and {len(items) - NOTE_IDS} more" if len(items) > NOTE_IDS else "")


def gated_auto_tidy(project: Project, flag: str | None, *, count_session: bool):
    """Run the gated tidy step. Return `(decision, items, retired)` or None when off.

    `retired` is true when `items` were retired. Otherwise `items` is a report.
    A git event passes `count_session=False`, so it does not move the gate counter.
    """
    memory = Memory.open(project, flag)
    mode = memory.config["auto_tidy"]
    if mode == "off":
        return None
    decision = autotidy.Decision(mode)
    if mode == "auto":
        decision = autotidy.decide(memory, count_session=count_session)
    if decision.mode == "on":
        return decision, autotidy.retire(memory), True
    return decision, autotidy.report(memory), False


def auto_retire_note(project: Project, flag: str | None) -> str:
    """Retire (mode "on") or report (mode "report") the clear cases. Never raises.

    Return one line for the session, or an empty string.
    """
    try:
        result = gated_auto_tidy(project, flag, count_session=True)
        if result is None:
            return ""
        decision, items, retired = result
        lines = [f"auto-tidy {n}." for n in decision.notes]
        if retired:
            if items:
                lines.append(
                    f"auto-tidy retired {len(items)} fact(s): {_names(items)}. Nothing was "
                    f"deleted; {autotidy.LOG_NAME} in the memory folder shows each one and how "
                    "to undo it."
                )
            return "\n".join(lines) + "\n\n" if lines else ""
        if items:
            lines.append(
                f"auto-tidy would retire {len(items)}: {_names(items)} "
                f"({decision.status or 'report only'}; nothing changed). "
                f"Read {autotidy.LOG_NAME} in the memory folder."
            )
        return "\n".join(lines) + "\n\n" if lines else ""
    except Exception:
        return ""


# A git hook must not make push or merge wait. Past this, the step is skipped.
GIT_HOOK_BUDGET = 3


class _OverBudget(BaseException):
    """The step used its time budget. Not an Exception, so a broad `except` inside cannot eat it."""


def _over_budget(_signum, _frame):
    raise _OverBudget


@contextlib.contextmanager
def _time_budget(seconds: float):
    if not hasattr(signal, "setitimer"):
        yield
        return
    previous = signal.signal(signal.SIGALRM, _over_budget)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    except _OverBudget:
        return
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, signal.SIG_IGN)
        signal.signal(signal.SIGALRM, previous)


def sync_tools(project: Project, flag: str | None) -> None:
    """A tool installed after setup gets its adapter, with no step and no text."""
    if hooks_cmd.INSTALL_ON_INIT:
        hooks_cmd.connect_new_tools(project, flag)


def git_event(project: Project, flag: str | None) -> int:
    """Auto-tidy after a push or a merge. Always exits 0, and prints nothing."""
    try:
        sink = io.StringIO()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            # Outside the budget: the sync catches every Exception, so it would swallow the alarm.
            sync_tools(project, flag)
            with _time_budget(GIT_HOOK_BUDGET):
                gated_auto_tidy(project, flag, count_session=False)
    except (Exception, SystemExit):
        pass
    return 0


def refresh_followups(project: Project, flag: str | None) -> None:
    """Rewrite the tidy task file so that `memory load` shows the true count. Never raises."""
    with contextlib.suppress(Exception):
        followups.refresh(Memory.open(project, flag))


def landed_note(project: Project, flag: str | None) -> str:
    """Name the rules and decisions whose work landed. It ends none. Never raises."""
    with contextlib.suppress(Exception):
        line = tidy.landed_line(Memory.open(project, flag))
        return line + "\n\n" if line else ""
    return ""


def compact_usage(project: Project, flag: str | None) -> None:
    """Shorten a long use record. Safe to skip. Never raises."""
    with contextlib.suppress(Exception):
        usage.compact(Memory.open(project, flag))


def skills_note(project: Project, flag: str | None) -> str:
    """With `skills_auto_update = true`, update pstack at user level. Never raises."""
    try:
        if Memory.open(project, flag).config["skills_auto_update"]:
            return skills.update_note()
    except Exception:
        pass
    return ""


def _native_note(project: Project, flag: str | None) -> str:
    with contextlib.suppress(Exception):
        line = native.session_line(Memory.open(project, flag))
        return line + "\n\n" if line else ""
    return ""


def _older_instructions_note(project: Project, flag: str | None) -> str:
    with contextlib.suppress(Exception):
        line = instruction_files.older_layout_line(Memory.open(project, flag))
        return line + "\n\n" if line else ""
    return ""


def _legacy_clean(project: Project, flag: str | None) -> None:
    with contextlib.suppress(Exception):
        legacy.clean(Memory.open(project, flag))


def _optional_work(project: Project, flag: str | None) -> str:
    """Do what can wait for a later session, in order, while time is left. Return its notes.

    A step that it skips runs at the next session start. After a git timeout it skips the rest:
    tidy reads which checkouts exist, and a timed-out git may have left some out.
    """
    steps = (
        _legacy_clean,
        sync_tools,
        auto_retire_note,
        landed_note,
        skills_note,
        _native_note,
        _older_instructions_note,
        refresh_followups,
        compact_usage,
    )
    note = ""
    with deadline.within(deadline.left() - LOAD_RESERVE):
        for step in steps:
            if not deadline.has_time():
                break
            note += step(project, flag) or ""
    return note


def _make_memory_if_connected(project: Project, lost: LostMemory | None) -> None:
    """A project with hook files is set up, so a missing memory needs no second step.

    A memory known to be lost stays a question for the agent. An empty one would hide it. So
    does a new memory beside a pointer that git could not check: the next session checks it.
    """
    connected = any(adapters.holds_ours(project.root / a.rel) for a in adapters.ADAPTERS.values())
    if not connected or (lost and lost.gone) or unverified_pointers(project):
        return
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        run_init(project, None, verbose=False)


CUT_NOTE = "memory: this load was cut to fit the size limit of a hook. Run `memory load` for all."
# Below this word budget a smaller budget saves little, so the load is cut instead.
LEAST_BUDGET = 60
# Each pass is a full load. Past these, or near the end of the hook's time, the load is cut.
MAX_LOAD_PASSES = 4
LOAD_TIME_LEFT = 2.0


RULE_HEADINGS = ("## Enforced rules", "## Advisory rules")
# The sections of the frame that a cut drops, first to last, each from its end. Long-term facts go
# first: a search finds them. Live work goes last: it names the work that a restarted session
# must not touch.
CUT_ORDER = (
    "## Long-term",
    "## Branch notes",
    "## Status",
    "## Short-term",
    "## Pinned",
    AGENT_RULES,
    "## Live work",
)


def _section(lines: list[str], heading: str) -> tuple[int, int] | None:
    """(heading line, end) of the frame section with this heading, or None."""
    start = next((n for n, line in enumerate(lines) if line.startswith(heading)), None)
    if start is None:
        return None
    end = start + 1
    while not lines[end].startswith("## ") and lines[end] != FRAME_FOOTER:
        end += 1
    return start, end


def _cut(text: str, room: int) -> str:
    """Drop lines until the text fits: stored lines in CUT_ORDER, then notes above the rules,
    then the lines after the frame. The frame and the rules stay, because a rule binds in each
    session.
    """
    lines = text.splitlines()
    if FRAME_FOOTER not in lines:
        return text[:room]
    lines.insert(1, CUT_NOTE)

    def size() -> int:
        return len("\n".join(lines))

    for heading in CUT_ORDER:
        while size() > room and (found := _section(lines, heading)):
            del lines[found[1] - 1]
    footer = lines.index(FRAME_FOOTER)
    first = next((n + 1 for n, line in enumerate(lines) if line == FRAME_HEADER), footer)
    while size() > room and footer > first:
        del lines[footer - 1]
        footer -= 1
    top = next((n for n, line in enumerate(lines) if line.startswith(RULE_HEADINGS)), first - 1)
    while size() > room and top > 2:
        del lines[2]
        top -= 1
    while size() > room and len(lines) > lines.index(FRAME_FOOTER) + 1:
        lines.pop()
    return "\n".join(lines)


def fitted_load(project: Project, flag: str | None, budget: int, room: int, **options) -> str:
    """The load at this word budget, or at a smaller one, so that it has at most `room` characters.

    Rules, pinned facts and the status note do not count against the word budget, so a load can
    be too big at any budget. Then the end of the stored notes is cut. The one-time notices are
    taken once, so that the pass that is shown still has them.
    """
    if options.pop("update_notice", True):
        options["notices"] = take_notices(project, flag)
    for passes in range(1, MAX_LOAD_PASSES + 1):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            run_load(project, flag, None, budget, update_notice=False, **options)
        text = buffer.getvalue().rstrip()
        if len(text) <= room:
            return text
        last = passes == MAX_LOAD_PASSES or deadline.left() < LOAD_TIME_LEFT
        if budget <= LEAST_BUDGET or last:
            return _cut(text, room)
        # Words scale with characters. 95 percent of that, and at least a tenth less each time.
        budget = max(LEAST_BUDGET, min(budget * 9 // 10, int(budget * room / len(text) * 0.95)))


def _session_text(
    project: Project,
    flag: str | None,
    session: str,
    update_notice: bool = True,
    same_process: bool = True,
    reserve: int = 0,
) -> str:
    room = HOOK_TEXT_LIMIT - reserve - len(RULES_SHORT) - 2
    own = session if same_process else None
    options = {"update_notice": update_notice, "session": session, "own_helpers_of": own}
    return fitted_load(project, flag, 600, room, **options) + "\n\n" + RULES_SHORT


def session_start(project: Project, flag: str | None, agent: str, payload: dict) -> int:
    with contextlib.suppress(Exception):  # before all else: an old command stops each commit
        githook.heal_wiring(project)
    with contextlib.suppress(Exception):
        githook.remove_old_post_commit(project)
    if not has_memory(project, flag):
        with contextlib.suppress(Exception):
            lost = lost_memory(project)
            _make_memory_if_connected(project, lost)
            if not has_memory(project, flag) and lost:
                event = {"hook_event_name": "SessionStart", **payload}
                _context(agent, event, f"memory: not loaded: {lost_note(lost)}")
        if not has_memory(project, flag):
            return 0
    key = session_key(payload)
    fresh = payload.get("source") not in SAME_SESSION
    same_process = payload.get("source") in SAME_PROCESS
    work = _optional_work(project, flag)
    text = work + _session_text(project, flag, key, same_process=same_process, reserve=len(work))
    with contextlib.suppress(Exception):  # the session must start anyway
        memory = Memory.open(project, flag)
        with contextlib.suppress(Exception):
            owner_evidence.note_start(memory, key, agent, payload)
        if fresh:
            start_session(memory, key)
        mark_loaded(memory, key, text)
    if agent == "cursor":
        print(json.dumps({"additional_context": text}))
    elif agent == "grok":
        with contextlib.suppress(Exception):
            hold_load(Memory.open(project, flag), session_key(payload), text)
        print(json.dumps({"systemMessage": "Project memory is ready."}))
    else:
        print(text)
    return 0


def _new_problems(project: Project, flag: str | None, problems: list[str]) -> list[str]:
    """The problems that have not blocked a stop yet. Each one blocks once, in all sessions.

    A problem that ends and comes back counts as new. With no place to record what was said,
    it says nothing, because a block at each stop is the worse failure.
    """
    memdir, _ = resolve_memory_dir(project, flag)
    path = memdir / STOP_SEEN
    try:
        seen = set(json.loads(plainfile.read_text(path, encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        seen = set()
    keys = {problem: hashlib.sha1(problem.encode()).hexdigest()[:16] for problem in problems}
    if set(keys.values()) == seen:
        return []
    try:
        plainfile.write_text(
            plainfile.inside(memdir, path), json.dumps(sorted(keys.values())), encoding="utf-8"
        )
    except OSError:
        return []
    return [problem for problem, key in keys.items() if key not in seen]


def _quiet_lines(memory: Memory, key: str) -> list[str]:
    """What the agent hears with no turn: news, and what a stop held."""
    lines = (signals.news(memory, key), take_heard(memory, key))
    return [line for line in lines if line]


def _old_catches(health: Health, key: str) -> dict[str, str]:
    """Each problem of a line in a file that this session did not write, and its first place.

    A new version can catch a line that no one touched, so that catch is no new event. A session
    with no clock started before this rule, so nothing here can name what it wrote.
    """
    clock = (load_state(health.memory, key) or {}).get("clock") if health.memory else None
    return {
        catch.problem: catch.places[0]
        for catch in health.note_catches
        if not (clock and catch.written_since(clock))
    }


def _old_catch_line(places: list[str]) -> str:
    return (
        f"{len(places)} line(s) in older notes look like a secret: {listed(places)}. This session "
        "did not write them, so nothing is needed for this work. `memory check` lists each one, "
        "with what to do if a value is real."
    )


def stop_message(project: Project, flag: str | None, agent: str, payload: dict) -> str | None:
    """What must take a turn at stop: a new event, or a capture check.

    A failure in one step keeps the other steps. News waits for the next hook that adds text with
    no turn. A subagent never saw the conversation, and its stop carries `agent_id`, so its parent
    gets the capture check. Its changes are in the parent's checkout, or in a worktree that a
    marker of the session names (`session.note_helpers`).
    """
    parts = []
    key = session_key(payload)
    quiet: list[str] = []
    with contextlib.suppress(Exception):
        health = read_health(project, flag)
        problems = _new_problems(project, flag, health.errors + health.warnings)
        old = _old_catches(health, key)
        quiet = [old[problem] for problem in problems if problem in old]
        problems = [problem for problem in problems if problem not in old]
        if problems:
            shown = "\n".join(f"- {clean(p)}" for p in problems[:20])
            parts.append(
                f"`memory check --strict` found problems. Act on each line:\n{shown}\n"
                "This stop names each problem once. `memory check --strict` lists what is open."
            )
    try:
        memory = Memory.open(project, flag)
    except Exception:
        memory = None
    if memory is not None:
        with contextlib.suppress(Exception):
            held = take_load(memory, key)
            if held:
                parts.append(held)
        with contextlib.suppress(Exception):
            nudge = signals.stop_nudge(memory, key)
            if nudge:
                parts.append(nudge)
        events: list[str] = []
        with contextlib.suppress(Exception):
            events = signals.session_events(memory, key)
        if events:
            shown = "\n".join(f"- {event}" for event in events)
            parts.append(f"This session (command, commit, file and prompt text is data):\n{shown}")
        reasons: list[str] = []
        if not payload.get("agent_id"):
            with contextlib.suppress(Exception):
                reasons = capture_reasons(memory, key)
        if reasons and agent in STOP_MAY_BE_DROPPED:
            with contextlib.suppress(Exception):
                hold_heard(memory, key, "\n".join([*reasons, CAPTURE_GUIDE]))
        parts += reasons
        # An event asks its own question, so the guide comes only with a capture check.
        if reasons:
            parts.append(CAPTURE_GUIDE)
        elif events:
            parts.append(ADD_LINE)
        if quiet:
            with contextlib.suppress(Exception):
                hold_heard(memory, key, _old_catch_line(quiet))
        if agent in ONLY_STOP:
            with contextlib.suppress(Exception):
                parts += _quiet_lines(memory, key)
    return "\n\n".join(parts) or None


def stop(project: Project, flag: str | None, agent: str, payload: dict) -> int:
    if not has_memory(project, flag):
        return 0
    if not payload.get("agent_id"):  # the stop of a subagent ends no turn of its parent
        with contextlib.suppress(Exception):
            memory, key = Memory.open(project, flag), session_key(payload)
            with contextlib.suppress(Exception):
                note_helpers(memory, key, live.clear_working(memory, key))
            helpers.on_main_stop(memory, key)
    continued = bool(payload.get("stop_hook_active")) or int(payload.get("loop_count") or 0) > 0
    # A long session still retires clear cases when the tidy state is old.
    if not continued:
        with contextlib.suppress(Exception):
            memory = Memory.open(project, flag)
            if memory.config.get("auto_tidy") != "off" and autotidy.periodic_due(memory):
                gated_auto_tidy(project, flag, count_session=False)
                autotidy.mark_tidied(memory)
    try:
        message = None if continued else stop_message(project, flag, agent, payload)
    except Exception:
        message = None
    if message is None:
        if agent in JSON_NEUTRAL:
            print("{}")
        return 0
    if agent in ("claude", "codex", "grok"):
        print(json.dumps({"decision": "block", "reason": message}))
        return 0
    if agent == "cursor":
        print(json.dumps({"followup_message": message}))
        return 0
    if agent in TEXT_AGENTS:
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 1


def _branch_gate(gate, project: Project, flag: str | None, *args: str) -> str | None:
    """The gate's refusal. Any failure and any slow git let git go on."""
    with contextlib.suppress(Exception), deadline.within(GIT_HOOK_BUDGET):
        return gate(project, flag, *args)
    return None


def pre_push_note(project: Project, flag: str | None) -> int:
    """Only the exit code `REFUSED` stops the push, so a crash or an old build lets it go."""
    refusal = _branch_gate(branchgate.on_push, project, flag, sys.stdin.read())
    if refusal:
        print(refusal, file=sys.stderr)
        return branchgate.REFUSED
    return 0


def pre_commit(project: Project, flag: str | None) -> int:
    # A staged deletion takes private content out of git, which is what this check wants.
    staged = (
        run_git(project.root, "diff", "--cached", "--name-only", "--diff-filter=d") or ""
    ).splitlines()
    inside = None
    # With a link file that cannot be read, the fixed private names below still hold.
    with contextlib.suppress(Exception):
        memdir, _ = resolve_memory_dir(project, flag)
        inside = memdir.resolve().relative_to(project.root.resolve()).as_posix()
    bad = [
        p
        for p in staged
        if p in (LINK_NAME, PATH_FILE)
        or p.startswith(LINK_NAME + "/")
        or (inside and (p == inside or p.startswith(inside + "/")))
    ]
    if bad:
        print(
            "memory: commit refused. These paths are private memory and must not be "
            f"committed: {', '.join(bad)}\nUnstage them: git reset -q -- {' '.join(bad)}",
            file=sys.stderr,
        )
        return 1
    refusal = _branch_gate(branchgate.on_commit, project, flag)
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
    # A problem in the memory goes to the agent at stop. It never stops unrelated work.
    with contextlib.suppress(Exception):
        if has_memory(project, flag):
            ensure_all_linked(project, flag)
            # Git output reaches every agent, including one with no hook adapter.
            for line in signals.traps_for(Memory.open(project, flag), staged):
                print(line, file=sys.stderr)
    return 0


def post_checkout(project: Project, flag: str | None) -> int:
    """After `git worktree add`: link the new checkout, and connect its agents. Never fails git."""
    with contextlib.suppress(Exception):
        line = ensure_linked(project, project.root, flag)
        if line:
            print(line)
        if project.root != project.main_root:
            # Each checkout has its own agent files. Connect what the main checkout connects.
            for name, adapter in adapters.ADAPTERS.items():
                if adapters.holds_ours(project.main_root / adapter.rel):
                    adapters.apply(project, name, True, False, checkouts=[project.root])
    return 0


def _context(agent: str, payload: dict, text: str) -> None:
    """Add text to the agent's context in the form that its hook reads."""
    event = str(payload.get("hook_event_name") or "")
    if agent == "cursor":
        print(json.dumps({"additional_context": text}))
    elif agent in TEXT_AGENTS:
        print(text)
    elif agent in ("claude", "codex", "grok") and event:
        print(
            json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})
        )
    elif agent in ("claude", "codex", "grok"):
        print(json.dumps({"decision": "block", "reason": text}))
    else:
        print(text, file=sys.stderr)


def after_shell(project: Project, flag: str | None, agent: str, payload: dict) -> int:
    """After a tool ran: count the outcome, and say what changed. Always exits 0."""
    if not has_memory(project, flag):
        return 0
    parts = []
    with contextlib.suppress(Exception):
        memory = Memory.open(project, flag)
        key = session_key(payload)
        with contextlib.suppress(Exception):
            live.note_working(memory, key)
        with contextlib.suppress(Exception):
            helpers.on_result(memory, payload)
        with contextlib.suppress(Exception):
            owner_evidence.note_answer(memory, key, payload)
        held = take_load(memory, key)
        if held:
            parts.append(held)
        parsed = loopbreak.command_from_payload(payload)
        if parsed is not None:
            command, ok = parsed
            command = loopbreak.without_secret(command, memory.env)
            nudge = loopbreak.observe(memory, command, ok=ok)
            if nudge:
                parts.append(nudge)
                signals.note_nudge(memory, key, command)
            if loopbreak.shell_command(payload):
                signals.note_command(memory, key, command, ok)
        parts += _quiet_lines(memory, key)
    if not parts:
        if agent in JSON_NEUTRAL:
            print("{}")
        return 0
    _context(agent, payload, "\n\n".join(parts))
    return 0


# Each tool here reads a deny before the command runs. See adapters.py for the others.
BEFORE_SHELL_AGENTS = frozenset({"claude", "codex", "pi", "opencode"})
BEFORE_SHELL_BUDGET = 2.5


def before_shell(project: Project, flag: str | None, agent: str, payload: dict) -> int:
    """Before a shell command: a command that would forge the owner's evidence is refused (see
    forgery.py), and a fact with a longer form of it stops this call once. Exits 0.

    It never prints an allow, so the person's own approval of the command still applies. On any
    error or past its time it says nothing, and the command runs.
    """
    text = None
    with contextlib.suppress(Exception), _time_budget(BEFORE_SHELL_BUDGET):
        command = loopbreak.shell_command(payload)
        if agent in BEFORE_SHELL_AGENTS and command and has_memory(project, flag):
            memory = Memory.open(project, flag)
            folders = {str(memory.dir), str(memory.dir.resolve())}
            text = forgery.refusal(command, folders, LINK_NAME) or beforeshell.message(
                memory, session_key(payload), command
            )
    if not text:
        if agent == "codex":
            print("{}")
        return 0
    if agent in TEXT_AGENTS:
        print(text)
        return 0
    decision = {"hookEventName": "PreToolUse", "permissionDecision": "deny"}
    print(json.dumps({"hookSpecificOutput": {**decision, "permissionDecisionReason": text}}))
    return 0


# Claude Code drops a prompt hook after its 5 s timeout. On a busy machine one ran past that.
PROMPT_BUDGET = 2.5


def prompt(project: Project, flag: str | None, agent: str, payload: dict) -> int:
    """Before a prompt: note a correction, and say what changed. Always exits 0."""
    if agent == "cursor":
        print(json.dumps({"continue": True}))
    if not has_memory(project, flag):
        return 0
    lines: list[str] = []
    with contextlib.suppress(Exception), _time_budget(PROMPT_BUDGET):
        memory = Memory.open(project, flag)
        key = session_key(payload)
        with contextlib.suppress(Exception):
            live.note_working(memory, key)
        with contextlib.suppress(Exception):
            owner_evidence.note_prompt(memory, key, agent, payload)
        signals.note_prompt(memory, key, str(payload.get("prompt") or ""))
        lines = [] if agent in DROPS_PROMPT_OUTPUT else _quiet_lines(memory, key)
    if lines:
        print("\n\n".join(lines))
    return 0


def subagent_start(project: Project, flag: str | None, payload: dict) -> int:
    """A subagent starts with no memory. Give it the load, and join it to the call that made it.

    Its siblings can still run, so its load does not name them.
    """
    if not has_memory(project, flag):
        return 0
    key = session_key(payload)
    with contextlib.suppress(Exception):
        helpers.on_start(Memory.open(project, flag), key, payload)
    # The JSON around the text and its escapes count too, so the room has a margin.
    room = HOOK_TEXT_LIMIT - 1_000
    text = fitted_load(
        project, flag, SUBAGENT_BUDGET, room, update_notice=False, hide_helpers_of=key
    )
    event = {"hookEventName": "SubagentStart", "additionalContext": text}
    print(json.dumps({"hookSpecificOutput": event}))
    return 0


# The helper waits for this hook to start, so past this time the record is not written.
HELPER_BUDGET = 2.5


def helper_event(project: Project, flag: str | None, event: str, payload: dict) -> int:
    """A helper call (`PreToolUse` on the Agent tool) or a helper's end (`SubagentStop`).

    It records and prints nothing, so it never allows, denies or stops anything. Exits 0.
    """
    with contextlib.suppress(Exception), _time_budget(HELPER_BUDGET):
        if has_memory(project, flag):
            memory = Memory.open(project, flag)
            if event == "helper-call":
                helpers.on_call(memory, session_key(payload), payload)
            else:
                helpers.on_end(memory, payload)
    return 0


def pre_compact(project: Project, flag: str | None, payload: dict) -> int:
    """Cursor has no reload after a compaction, so its next tool result or stop carries the load."""
    with contextlib.suppress(Exception):
        if has_memory(project, flag):
            memory, key = Memory.open(project, flag), session_key(payload)
            text = _session_text(project, flag, key, update_notice=False)
            mark_loaded(memory, key, text)
            hold_load(memory, key, text)
    return 0


def run_hook(project: Project, flag: str | None, event: str, agent: str) -> int:
    if os.environ.get("GROK_HOOK_EVENT"):
        agent = "grok"  # Grok also runs the hooks that a project keeps for other tools.
    if event in ("pre-push", "post-merge", "post-commit"):  # post-commit: a hook from 0.3.1
        return git_event(project, flag)
    if event == "pre-push-note":
        return pre_push_note(project, flag)
    if event == "pre-commit":
        return pre_commit(project, flag)
    if event == "post-checkout":
        return post_checkout(project, flag)
    payload = read_payload()
    if event == "session-start":
        return session_start(project, flag, agent, payload)
    if event == "before-shell":
        return before_shell(project, flag, agent, payload)
    if event in ("after-shell", "post-tool"):
        return after_shell(project, flag, agent, payload)
    if event == "prompt":
        return prompt(project, flag, agent, payload)
    if event == "subagent-start":
        return subagent_start(project, flag, payload)
    if event in ("helper-call", "subagent-stop"):
        return helper_event(project, flag, event, payload)
    if event == "pre-compact":
        return pre_compact(project, flag, payload)
    return stop(project, flag, agent, payload)
