"""Three identical command failures ask the agent to stop, check, or ask."""

from __future__ import annotations

import io
import json

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.session import note_failure

CMD = "pytest tests/test_loop_breaker.py"


def start(capsys, monkeypatch, sid="s1"):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": sid})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0


def stop(capsys, monkeypatch, sid="s1"):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": sid})))
    capsys.readouterr()
    code = main(["hook", "stop", "--agent", "claude"])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_three_identical_failures_say_stop_check_or_ask(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    memory = Memory.open(find_project(), None)
    for _ in range(3):
        note_failure(memory, "s1", CMD)
    code, out, _ = stop(capsys, monkeypatch)
    assert code == 0
    reason = json.loads(out)["reason"].lower()
    assert "stop" in reason
    assert "check" in reason
    assert "ask" in reason


def test_two_failures_stay_quiet(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    memory = Memory.open(find_project(), None)
    note_failure(memory, "s1", CMD)
    note_failure(memory, "s1", CMD)
    code, out, _ = stop(capsys, monkeypatch)
    assert code == 0
    assert "block" not in out


def test_a_different_command_resets_the_streak(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    memory = Memory.open(find_project(), None)
    note_failure(memory, "s1", "pytest tests/test_a.py")
    note_failure(memory, "s1", "pytest tests/test_a.py")
    note_failure(memory, "s1", "pytest tests/test_b.py")
    _, out, _ = stop(capsys, monkeypatch)
    assert "block" not in out
