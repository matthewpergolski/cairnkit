"""Break a repeated failing shell/tool loop after three identical failures.

State lives in `<memory>/.loop-breaker.json`: last command + fail streak.
A success or a different command resets the streak. On the third identical
failure the hook returns a short nudge: stop, check memory, or ask.

Each agent reports a failure in its own way (checked against its public docs):

- Claude Code: `PostToolUse` fires only on success. `PostToolUseFailure` fires on a failure.
- Cursor: `postToolUseFailure` fires on a failure. `afterShellExecution` has no exit code, so
  it says nothing about the outcome.
- Codex: `PostToolUse` fires for each result. The exit code is in the text of the result.
- Pi and OpenCode: the generated adapter names the event from the exit status, with an empty
  response.
- Gap: a generic agent, or any agent with no hook adapter, cannot report a command. Stop still
  shows a recorded streak.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from cairnkit.memory import Memory
from cairnkit.store import locked

STATE_NAME = ".loop-breaker.json"
LOCK_NAME = ".loop-breaker.lock"
THRESHOLD = 3
NUDGE = (
    "The same command failed 3 times in a row. Stop retrying it. "
    "Find the cause, search the memory for it (`memory search WORDS`), or ask the person."
)


def _path(memory: Memory) -> Path:
    return memory.dir / STATE_NAME


def _load(memory: Memory) -> dict:
    try:
        data = json.loads(_path(memory).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(memory: Memory, data: dict) -> None:
    _path(memory).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def normalize_command(command: str) -> str:
    return " ".join(str(command or "").split())


def current_command(memory: Memory) -> str:
    return str(_load(memory).get("command") or "")


def observe(memory: Memory, command: str, *, ok: bool) -> str | None:
    """Record one command outcome. Return the nudge text on the third fail, else None."""
    cmd = normalize_command(command)
    if not cmd:
        return None
    with locked(memory.dir / LOCK_NAME):
        data = _load(memory)
        if ok or data.get("command") != cmd:
            data = {"command": cmd, "streak": 0 if ok else 1}
            _save(memory, data)
            return None
        streak = int(data.get("streak", 0)) + 1
        data = {"command": cmd, "streak": streak}
        _save(memory, data)
        if streak >= THRESHOLD:
            return NUDGE
        return None


EXIT_TEXT = re.compile(r"(?i)exit(?:ed)?(?: with)?(?: code)?[: ]+(-?\d+)")


def shell_command(payload: dict) -> str:
    """The shell command in a hook payload, or an empty string for any other tool."""
    return normalize_command(
        payload.get("command")
        or payload.get("cmd")
        or (payload.get("tool_input") or {}).get("command")
        or (payload.get("input") or {}).get("command")
        or ""
    )


def command_from_payload(payload: dict) -> tuple[str, bool] | None:
    """Extract (command, ok) from a hook payload. Return None when the outcome is not known."""
    if not isinstance(payload, dict):
        return None
    shell = shell_command(payload)
    command = shell or normalize_command(payload.get("tool_name") or "")
    if not command:
        return None
    event = str(payload.get("hook_event_name") or "")
    if event in ("PostToolUseFailure", "postToolUseFailure"):
        return None if payload.get("is_interrupt") else (command, False)
    if "exit_code" in payload:
        return command, int(payload.get("exit_code") or 0) == 0
    status = str(payload.get("status") or payload.get("tool_response_status") or "").lower()
    if status in ("error", "failed", "failure"):
        return command, False
    if status in ("success", "ok", "completed"):
        return command, True
    result = payload.get("tool_response") or payload.get("result") or ""
    if isinstance(result, dict) and "exit_code" in result:
        return command, int(result.get("exit_code") or 0) == 0
    if isinstance(result, dict) and result.get("error"):
        return command, False
    if payload.get("error"):
        return command, False
    if isinstance(result, str):
        found = EXIT_TEXT.search(result[:400])
        if found:
            return command, int(found.group(1)) == 0
    # A success from another tool must not reset the streak of the failing command.
    # Pi and OpenCode send an empty response, because their event name holds the outcome.
    if event == "PostToolUse" and shell and (isinstance(result, dict) or not result):
        return command, True
    return None
