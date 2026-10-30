"""Loop breaker: three identical command failures in a row nudge the agent.

Harness coverage expected by this suite (and `cairnkit.loopbreak` docstring):

- Cursor: wired on `afterShellExecution` when the adapter installs hooks.
- Claude: wired on `PostToolUse` when the NestedAdapter installs hooks.
- Codex: same PostToolUse shape as Claude when the adapter installs hooks.
- Gap: no reliable per-tool failure signal for the generic agent; stop-only.
"""

from __future__ import annotations

import io
import json

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project


def test_three_identical_failures_nudge_and_reset_on_success(repo, mem):
    from cairnkit import loopbreak

    memory = Memory.open(find_project(), None)
    assert loopbreak.observe(memory, "pytest -q", ok=False) is None
    assert loopbreak.observe(memory, "pytest -q", ok=False) is None
    nudge = loopbreak.observe(memory, "pytest -q", ok=False)
    assert nudge is not None
    assert "stop" in nudge.lower() or "memory" in nudge.lower() or "ask" in nudge.lower()
    state = json.loads((mem / loopbreak.STATE_NAME).read_text())
    assert state["streak"] == 3
    assert state["command"] == "pytest -q"
    # Success resets.
    assert loopbreak.observe(memory, "pytest -q", ok=True) is None
    state = json.loads((mem / loopbreak.STATE_NAME).read_text())
    assert state["streak"] == 0


def test_different_command_resets_the_streak(repo, mem):
    from cairnkit import loopbreak

    memory = Memory.open(find_project(), None)
    loopbreak.observe(memory, "cmd-a", ok=False)
    loopbreak.observe(memory, "cmd-a", ok=False)
    assert loopbreak.observe(memory, "cmd-b", ok=False) is None
    state = json.loads((mem / loopbreak.STATE_NAME).read_text())
    assert state["command"] == "cmd-b"
    assert state["streak"] == 1


def test_hook_after_shell_emits_nudge_on_third_fail(repo, mem, monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "command": "make test",
                    "status": "error",
                    "exit_code": 1,
                    "session_id": "s1",
                }
            )
        ),
    )
    # Two prior fails.
    from cairnkit import loopbreak

    memory = Memory.open(find_project(), None)
    loopbreak.observe(memory, "make test", ok=False)
    loopbreak.observe(memory, "make test", ok=False)
    capsys.readouterr()
    assert main(["hook", "after-shell", "--agent", "cursor"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "followup_message" in data or "additional_context" in data or "decision" in data
    blob = json.dumps(data).lower()
    assert "stop" in blob or "memory" in blob or "ask" in blob


def test_cursor_install_wires_after_shell_execution(repo, mem, capsys):
    capsys.readouterr()
    assert main(["hooks", "install", "--agent", "cursor"]) == 0
    path = repo / ".cursor" / "hooks.json"
    assert path.is_file()
    data = json.loads(path.read_text())
    events = data.get("hooks", {})
    assert "afterShellExecution" in events
    commands = " ".join(h.get("command", "") for h in events["afterShellExecution"])
    assert "after-shell" in commands


def test_claude_install_wires_post_tool_use(repo, mem, capsys):
    capsys.readouterr()
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    path = repo / ".claude" / "settings.local.json"
    data = json.loads(path.read_text())
    events = data.get("hooks", {})
    assert "PostToolUse" in events
    blob = json.dumps(events["PostToolUse"])
    assert "after-shell" in blob or "post-tool" in blob


def test_coverage_notes_document_generic_gap():
    import cairnkit.loopbreak as lb

    doc = lb.__doc__ or ""
    compact = doc.lower().replace("_", "").replace(" ", "").replace("-", "")
    assert "cursor" in doc.lower() and "aftershellexecution" in compact
    assert "claude" in doc.lower() and "posttooluse" in compact
    assert "codex" in doc.lower()
    assert "gap" in doc.lower() and "generic" in doc.lower()
