"""`memory hook EVENT --agent NAME`: the command that agent hooks call.

Each agent tool reads hook output in its own format. This module keeps the
logic generic and only formats the output per agent. It never blocks a
session start, and it never crashes a stop: on an unexpected error it
prints the neutral output and exits 0.
"""

from __future__ import annotations

import contextlib
import io
import json
import signal
import sys

from cairnkit import autotidy, followups, legacy, loopbreak, signals, skills, usage
from cairnkit.check import check_links, check_records
from cairnkit.discover import RULES_SHORT
from cairnkit.init import ensure_all_linked, ensure_linked
from cairnkit.load import run_load
from cairnkit.memory import Memory, MemoryMissing
from cairnkit.paths import LINK_NAME, PATH_FILE, Project, resolve_memory_dir, run_git
from cairnkit.session import (
    mark_compacted,
    mark_loaded,
    needs_reminder,
    reminder_hint,
    reminder_text,
    start_session,
)

NOTE_IDS = 10
# Agents that need a JSON empty object when memory exists but there is nothing to say.
JSON_NEUTRAL = frozenset({"codex", "cursor"})


def has_memory(project: Project, flag: str | None) -> bool:
    """True only when `memory init` has created a facts folder. Never creates paths."""
    memdir, _ = resolve_memory_dir(project, flag)
    return (memdir / "facts").is_dir()


def read_payload() -> dict:
    try:
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


class _OverBudget(Exception):
    """The git-hook step used its time budget."""


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


def git_event(project: Project, flag: str | None) -> int:
    """Auto-tidy after a push or a merge. Always exits 0, and prints nothing."""
    try:
        with _time_budget(GIT_HOOK_BUDGET):
            sink = io.StringIO()
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                gated_auto_tidy(project, flag, count_session=False)
    except (Exception, SystemExit):
        pass
    return 0


def refresh_followups(project: Project, flag: str | None) -> None:
    """Rewrite the tidy task file so that `memory load` shows the true count. Never raises."""
    with contextlib.suppress(Exception):
        followups.refresh(Memory.open(project, flag))


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


def session_start(project: Project, flag: str | None, agent: str, payload: dict) -> int:
    if not has_memory(project, flag):
        return 0
    with contextlib.suppress(Exception):
        legacy.clean(Memory.open(project, flag))
    note = auto_retire_note(project, flag) + skills_note(project, flag)
    refresh_followups(project, flag)
    compact_usage(project, flag)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        run_load(project, flag, None, 600, agent=agent, record=True)
    text = note + buffer.getvalue().rstrip() + "\n\n" + RULES_SHORT
    with contextlib.suppress(Exception):  # the session must start anyway
        memory = Memory.open(project, flag)
        key = session_key(payload)
        if payload.get("source") != "compact":  # a compaction is the same session
            start_session(memory, key)
        mark_loaded(memory, key, text)
    if agent == "cursor":
        print(json.dumps({"additional_context": text}))
    else:
        print(text)
    return 0


def _strict_problems(project: Project, flag: str | None) -> list[str]:
    memdir, _ = resolve_memory_dir(project, flag)
    if not memdir.is_dir():
        return []
    ensure_all_linked(project, flag)
    problems = check_links(project, memdir)
    memory = Memory.open(project, flag)
    errors, warnings = check_records(memory)
    return problems + errors + warnings


def stop_message(project: Project, flag: str | None, payload: dict) -> str | None:
    problems = _strict_problems(project, flag)
    parts = []
    if problems:
        shown = "\n".join(f"- {p}" for p in problems[:20])
        parts.append(f"`memory check --strict` found problems. Fix them:\n{shown}")
    try:
        memory = Memory.open(project, flag)
    except MemoryMissing:
        memory = None
    if memory is not None:
        with contextlib.suppress(Exception):
            from cairnkit.session import loop_nudge

            nudge = loop_nudge(memory)
            if nudge:
                parts.append(nudge)
        key = session_key(payload)
        with contextlib.suppress(Exception):
            line = signals.news(memory, key)
            if line:
                parts.append(line)
        events: list[str] = []
        with contextlib.suppress(Exception):
            events = signals.session_events(memory, key)
        if events:
            shown = "\n".join(f"- {event}" for event in events)
            parts.append(f"This session:\n{shown}\n{reminder_hint()}")
        elif needs_reminder(memory, key):
            parts.append(reminder_text(memory))
    return "\n\n".join(parts) or None


def stop(project: Project, flag: str | None, agent: str, payload: dict) -> int:
    if not has_memory(project, flag):
        return 0
    continued = bool(payload.get("stop_hook_active")) or int(payload.get("loop_count") or 0) > 0
    # A long session still retires clear cases when the tidy state is old.
    if not continued:
        with contextlib.suppress(Exception):
            memory = Memory.open(project, flag)
            if memory.config.get("auto_tidy") != "off" and autotidy.periodic_due(memory):
                gated_auto_tidy(project, flag, count_session=False)
                autotidy.mark_tidied(memory)
    try:
        message = None if continued else stop_message(project, flag, payload)
    except Exception:
        message = None
    if message is None:
        if agent in JSON_NEUTRAL:
            print("{}")
        return 0
    if agent in ("claude", "codex"):
        print(json.dumps({"decision": "block", "reason": message}))
        return 0
    if agent == "cursor":
        print(json.dumps({"followup_message": message}))
        return 0
    print(message, file=sys.stderr)
    return 1


def pre_commit(project: Project, flag: str | None) -> int:
    staged = (run_git(project.root, "diff", "--cached", "--name-only") or "").splitlines()
    memdir, _ = resolve_memory_dir(project, flag)
    inside = None
    with contextlib.suppress(ValueError):
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
    # A problem in the memory goes to the agent at stop. It never stops unrelated work.
    with contextlib.suppress(Exception):
        if has_memory(project, flag):
            ensure_all_linked(project, flag)
    return 0


def post_checkout(project: Project, flag: str | None) -> int:
    """After `git worktree add`: link the new checkout. Never fails the git command."""
    with contextlib.suppress(Exception):
        line = ensure_linked(project, project.root, flag)
        if line:
            print(line)
    return 0


def _context(agent: str, payload: dict, text: str) -> None:
    """Add text to the agent's context in the form that its hook reads."""
    event = str(payload.get("hook_event_name") or "")
    if agent == "cursor":
        print(json.dumps({"additional_context": text, "followup_message": text}))
    elif agent in ("claude", "codex") and event:
        print(
            json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})
        )
    elif agent in ("claude", "codex"):
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
        parsed = loopbreak.command_from_payload(payload)
        if parsed is not None:
            command, ok = parsed
            nudge = loopbreak.observe(memory, command, ok=ok)
            if nudge:
                parts.append(nudge)
            signals.note_command(memory, key, loopbreak.normalize_command(command), ok)
        line = signals.news(memory, key)
        if line:
            parts.append(line)
    if not parts:
        if agent in JSON_NEUTRAL:
            print("{}")
        return 0
    _context(agent, payload, "\n\n".join(parts))
    return 0


def prompt(project: Project, flag: str | None, agent: str, payload: dict) -> int:
    """Before a prompt: say what changed in the memory or the work. Always exits 0."""
    if not has_memory(project, flag):
        return 0
    with contextlib.suppress(Exception):
        line = signals.news(Memory.open(project, flag), session_key(payload))
        if line:
            print(line)
    return 0


def pre_compact(project: Project, flag: str | None, payload: dict) -> int:
    """A tool with no reload after a compaction hears about it at its next stop."""
    with contextlib.suppress(Exception):
        if has_memory(project, flag):
            mark_compacted(Memory.open(project, flag), session_key(payload))
    return 0


def run_hook(project: Project, flag: str | None, event: str, agent: str) -> int:
    if event in ("pre-push", "post-merge", "post-commit"):  # post-commit: a hook from 0.3.1
        return git_event(project, flag)
    if event == "pre-commit":
        return pre_commit(project, flag)
    if event == "post-checkout":
        return post_checkout(project, flag)
    payload = read_payload()
    if event == "session-start":
        return session_start(project, flag, agent, payload)
    if event in ("after-shell", "post-tool"):
        return after_shell(project, flag, agent, payload)
    if event == "prompt":
        return prompt(project, flag, agent, payload)
    if event == "pre-compact":
        return pre_compact(project, flag, payload)
    return stop(project, flag, agent, payload)
