"""Cursor reads text at a tool result, per its docs. A compaction and news arrive there."""

from __future__ import annotations

import io
import json

from conftest import make_fact, write_facts

from cairnkit import adapters
from cairnkit.cli import main


def hook(capsys, monkeypatch, event: str, payload: dict) -> str:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    capsys.readouterr()
    assert main(["hook", event, "--agent", "cursor"]) == 0
    return capsys.readouterr().out


def tool(command: str = "ls", event: str = "postToolUse") -> dict:
    return {
        "session_id": "s",
        "hook_event_name": event,
        "tool_name": "Shell",
        "tool_input": {"command": command},
    }


def test_the_hooks_read_by_cursor_are_wired(repo, mem):
    assert main(["hooks", "install", "--agent", "cursor"]) == 0
    hooks = json.loads((repo / ".cursor" / "hooks.json").read_text())["hooks"]
    assert "afterShellExecution" not in hooks, "its output is not read, so news sent there is lost"
    assert hooks["postToolUse"][0]["matcher"] == "Shell|Write|Delete"
    assert "after-shell" in hooks["postToolUse"][0]["command"]
    assert "hook prompt" in hooks["beforeSubmitPrompt"][0]["command"]


def test_the_memory_comes_back_at_the_first_tool_after_a_compaction(repo, mem, capsys, monkeypatch):
    write_facts(mem, [make_fact("f-20261001-0001", "The port is 7643.", pinned=True)])
    hook(capsys, monkeypatch, "session-start", {"session_id": "s", "source": "startup"})
    assert hook(capsys, monkeypatch, "pre-compact", {"session_id": "s"}) == ""
    out = json.loads(hook(capsys, monkeypatch, "after-shell", tool()))
    assert "The port is 7643." in out["additional_context"]
    assert set(out) == {"additional_context"}, "these events document no other field"
    assert json.loads(hook(capsys, monkeypatch, "after-shell", tool())) == {}


def test_with_no_tool_the_memory_comes_back_at_stop(repo, mem, capsys, monkeypatch):
    write_facts(mem, [make_fact("f-20261001-0001", "The port is 7643.", pinned=True)])
    hook(capsys, monkeypatch, "session-start", {"session_id": "s", "source": "startup"})
    hook(capsys, monkeypatch, "pre-compact", {"session_id": "s"})
    out = json.loads(hook(capsys, monkeypatch, "stop", {"session_id": "s"}))
    assert "The port is 7643." in out["followup_message"]


def test_a_pass_after_failures_is_seen(repo, mem, capsys, monkeypatch):
    hook(capsys, monkeypatch, "session-start", {"session_id": "s", "source": "startup"})
    for _ in range(2):
        hook(capsys, monkeypatch, "after-shell", tool("make", "postToolUseFailure"))
    hook(capsys, monkeypatch, "after-shell", tool("make"))
    out = json.loads(hook(capsys, monkeypatch, "stop", {"session_id": "s"}))
    assert "`make` failed 2 times, then passed" in out["followup_message"]


def test_pi_sends_the_prompt_of_the_owner():
    assert 'hook("prompt", { session_id: key(ctx), prompt: event.prompt })' in adapters.PI_EXTENSION
