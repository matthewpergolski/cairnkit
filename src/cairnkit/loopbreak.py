"""Break a repeated failing shell/tool loop after three identical failures.

State lives in `<memory>/.loop-breaker.json`: last command + fail streak.
A success or a different command resets the streak. On the third identical
failure the hook returns a short nudge: stop, check memory, or ask.

Harness coverage (wired where the adapter schema allows):

- Cursor: `afterShellExecution` → `memory hook after-shell --agent cursor`.
- Claude: `PostToolUse` → `memory hook after-shell --agent claude` (Bash/shell
  tool results; other tools are ignored when no command/exit is present).
- Codex: same NestedAdapter `PostToolUse` shape as Claude.
- Gap: the generic agent has no after-shell / PostToolUse hook surface, so
  the loop breaker does not run there (stop reminder only).
- Gap: OpenCode, Pi, and Grok Build have no hook adapter, so they cannot
  observe a command failure. Stop still shows the nudge when something else
  recorded the streak.
"""

from __future__ import annotations

import json
from pathlib import Path

from cairnkit.memory import Memory
from cairnkit.store import locked

STATE_NAME = ".loop-breaker.json"
LOCK_NAME = ".loop-breaker.lock"
THRESHOLD = 3
NUDGE = (
    "The same command failed 3 times in a row. Stop retrying it. "
    "Run `memory check`, then fix the cause or ask the person what to do next."
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


def command_from_payload(payload: dict) -> tuple[str, bool] | None:
    """Extract (command, ok) from a Cursor afterShell / Claude PostToolUse payload.

    Returns None when the payload is not a shell/tool failure signal we understand.
    """
    if not isinstance(payload, dict):
        return None
    command = (
        payload.get("command")
        or payload.get("cmd")
        or (payload.get("tool_input") or {}).get("command")
        or (payload.get("input") or {}).get("command")
        or payload.get("tool_name")
        or ""
    )
    if not command and payload.get("tool_name"):
        command = str(payload.get("tool_name"))
    command = normalize_command(command)
    if not command:
        return None
    if "exit_code" in payload:
        ok = int(payload.get("exit_code") or 0) == 0
        return command, ok
    status = str(payload.get("status") or payload.get("tool_response_status") or "").lower()
    if status in ("error", "failed", "failure"):
        return command, False
    if status in ("success", "ok", "completed"):
        return command, True
    # Claude PostToolUse often nests the result.
    result = payload.get("tool_response") or payload.get("result") or ""
    if isinstance(result, dict):
        if "exit_code" in result:
            return command, int(result.get("exit_code") or 0) == 0
        err = result.get("error") or result.get("stderr")
        if err:
            return command, False
    if payload.get("error"):
        return command, False
    # Unknown outcome: ignore rather than false-positive.
    return None
