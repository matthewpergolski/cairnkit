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
import sys

from cairnkit import autotidy, followups, skills, usage
from cairnkit.check import check_links, check_records
from cairnkit.init import link_here
from cairnkit.load import run_load
from cairnkit.memory import Memory, MemoryMissing
from cairnkit.paths import LINK_NAME, PATH_FILE, Project, resolve_memory_dir, run_git
from cairnkit.session import needs_reminder, start_session

NOTE_IDS = 10

RULES_SHORT = """\
Memory rules: record what a later session needs with `memory add` (decisions,
traps, lessons: long-term; working notes: `--short --until-merged`). To change
a fact, add a newer one (`--supersedes ID`) or mark it `expired` or `wrong`
with `memory change`. Never store secrets. Never edit memory files by hand.
Run `memory instructions` for the full rules."""

REMINDER = """\
Before you finish: you changed the work in this session and wrote no memory.
Record what a later session needs, then finish:
- a decision, trap or lesson: `memory add "..." --kind decision|trap|lesson --area AREA --basis seen|told|guess --source commit:HASH|file:PATH`
- a working note for this branch: `memory add "..." --short --until-merged --area AREA --basis seen --source session:DATE`
- a fact that is now wrong or replaced: `memory change ID --status wrong|expired --reason "..."` or `memory add "..." --supersedes ID`
If nothing is worth recording, say so and finish."""  # noqa: E501


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


def auto_retire_note(project: Project, flag: str | None) -> str:
    """Retire (mode "on") or report (mode "report") the clear cases. Never raises.

    Return one line for the session, or an empty string.
    """
    try:
        memory = Memory.open(project, flag)
        mode = memory.config["auto_tidy"]
        if mode == "off":
            return ""
        decision = autotidy.Decision(mode)
        if mode == "auto":
            decision = autotidy.decide(memory)
        if decision.mode == "on":
            retired = autotidy.retire(memory)
            lines = [f"auto-tidy {n}." for n in decision.notes]
            if retired:
                lines.append(
                    f"auto-tidy retired {len(retired)} fact(s): {_names(retired)}. Nothing was "
                    f"deleted; {autotidy.LOG_NAME} in the memory folder shows each one and how "
                    "to undo it."
                )
            return "\n".join(lines) + "\n\n" if lines else ""
        lines = [f"auto-tidy {n}." for n in decision.notes]
        found = autotidy.report(memory)
        if found:
            lines.append(
                f"auto-tidy would retire {len(found)}: {_names(found)} "
                f"({decision.status or 'report only'}; nothing changed). "
                f"Read {autotidy.LOG_NAME} in the memory folder."
            )
        return "\n".join(lines) + "\n\n" if lines else ""
    except Exception:
        return ""


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
    note = auto_retire_note(project, flag) + skills_note(project, flag)
    refresh_followups(project, flag)
    compact_usage(project, flag)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        run_load(project, flag, None, 600, agent=agent, record=True)
    text = note + buffer.getvalue().rstrip() + "\n\n" + RULES_SHORT
    with contextlib.suppress(Exception):  # the session must start anyway
        start_session(Memory.open(project, flag), session_key(payload))
    if agent == "cursor":
        print(json.dumps({"additional_context": text}))
    else:
        print(text)
    return 0


def _strict_problems(project: Project, flag: str | None) -> list[str]:
    memdir, _ = resolve_memory_dir(project, flag)
    if not memdir.is_dir():
        return []
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
    if memory is not None and needs_reminder(memory, session_key(payload)):
        parts.append(REMINDER)
    return "\n\n".join(parts) or None


def stop(project: Project, flag: str | None, agent: str, payload: dict) -> int:
    neutral = {"claude": None, "codex": "{}", "cursor": "{}", "generic": None}[agent]
    continued = bool(payload.get("stop_hook_active")) or int(payload.get("loop_count") or 0) > 0
    try:
        message = None if continued else stop_message(project, flag, payload)
    except Exception:
        message = None
    if message is None:
        if neutral:
            print(neutral)
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
    if not memdir.is_dir():
        return 0
    errors = check_links(project, memdir) + check_records(Memory.open(project, flag))[0]
    if errors:
        shown = "\n".join(f"  {e}" for e in errors[:10])
        print(f"memory: commit refused. `memory check` found problems:\n{shown}", file=sys.stderr)
        return 1
    return 0


def post_checkout(project: Project, flag: str | None) -> int:
    """After `git worktree add`: link the new checkout. Never fails the git command."""
    with contextlib.suppress(Exception):
        line = link_here(project, flag)
        if line:
            print(line)
    return 0


def run_hook(project: Project, flag: str | None, event: str, agent: str) -> int:
    if event == "pre-commit":
        return pre_commit(project, flag)
    if event == "post-checkout":
        return post_checkout(project, flag)
    payload = read_payload()
    if event == "session-start":
        return session_start(project, flag, agent, payload)
    return stop(project, flag, agent, payload)
