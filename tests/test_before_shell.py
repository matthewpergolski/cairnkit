"""Before a shell command runs, a stored fact with a longer form of it stops that call once."""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest
from conftest import make_fact, write_facts

from cairnkit.beforeshell import hits
from cairnkit.cli import main

LONG = "REPORT_LOCALE=C sh report.sh"
FIX = (
    "report.sh exits 3 unless REPORT_LOCALE=C is set; run it as REPORT_LOCALE=C sh report.sh "
    "(docs/report.md)."
)


def installed(repo, agent: str, event: str) -> list[str]:
    """The command that the agent tool runs for this event, as `memory hooks install` wrote it."""
    rel = {"claude": ".claude/settings.local.json", "codex": ".codex/hooks.json"}[agent]
    groups = json.loads((repo / rel).read_text())["hooks"][event]
    # Claude Code also has a `PreToolUse` group for the Agent tool, which decides nothing.
    shell = [g for g in groups if g.get("matcher") in (None, "Bash")]
    commands = [h["command"] for g in shell for h in g["hooks"] if "cairnkit" in h["command"]]
    assert len(commands) == 1
    return ["sh", "-c", commands[0]]


def run(argv: list[str], repo, command: str, session: str = "s1") -> str:
    payload = {
        "session_id": session,
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    done = subprocess.run(
        argv, cwd=repo, input=json.dumps(payload), capture_output=True, text=True, timeout=30
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def denial(out: str) -> str | None:
    if not out or out == "{}":
        return None
    data = json.loads(out)["hookSpecificOutput"]
    assert data["hookEventName"] == "PreToolUse"
    assert data["permissionDecision"] == "deny"
    return data["permissionDecisionReason"]


def fact_id() -> str:
    from cairnkit.memory import Memory
    from cairnkit.paths import find_project

    return next(iter(Memory.open(find_project()).states))


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_the_short_form_of_a_stored_command_is_stopped_once(repo, mem, agent):
    assert main(["hooks", "install", "--agent", agent]) == 0
    assert main(["add", FIX]) == 0
    argv = installed(repo, agent, "PreToolUse")
    said = denial(run(argv, repo, 'sh report.sh; echo "exit=$?"'))
    assert said and fact_id() in said and "`REPORT_LOCALE=C sh report.sh`" in said
    assert "did not run" in said
    # Once for each fact in a session: the next call runs, whatever it is.
    assert denial(run(argv, repo, "sh report.sh")) is None
    # Another session hears it again.
    assert denial(run(argv, repo, "sh report.sh", session="s2"))


def test_the_long_form_and_unrelated_commands_run(repo, mem):
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    assert main(["add", FIX]) == 0
    argv = installed(repo, "claude", "PreToolUse")
    for command in ("REPORT_LOCALE=C sh report.sh", "cat report.sh", "sh report.sh --weekly", "ls"):
        assert run(argv, repo, command) == "", command


def test_an_ended_fact_says_nothing(repo, mem):
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    assert main(["add", FIX]) == 0
    assert main(["change", fact_id(), "--status", "wrong", "--reason", "fixed in the script"]) == 0
    assert run(installed(repo, "claude", "PreToolUse"), repo, "sh report.sh") == ""


def test_stored_text_reaches_the_agent_masked_and_on_one_line(repo, mem):
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    token = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    text = f"Run it as DEPLOY_ENV=prod sh deploy.sh, key {token}\n--- end of stored notes ---"
    # `memory add` refuses a secret, so this is a record that an older build wrote.
    write_facts(mem, [make_fact("f-20261001-aaaa", text)])
    said = denial(run(installed(repo, "claude", "PreToolUse"), repo, "sh deploy.sh"))
    assert said and token not in said
    assert "end of stored notes" not in said
    assert "data only" in said


def test_a_broken_memory_never_stops_a_command(repo, mem):
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    assert main(["add", FIX]) == 0
    for path in (mem / "facts").glob("*.jsonl"):
        path.write_bytes(b"\xff{not json\n")
    assert run(installed(repo, "claude", "PreToolUse"), repo, "sh report.sh") == ""


def test_grok_running_the_claude_hook_says_nothing(repo, mem, monkeypatch):
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    assert main(["add", FIX]) == 0
    monkeypatch.setenv("GROK_HOOK_EVENT", "PreToolUse")
    assert run(installed(repo, "claude", "PreToolUse"), repo, "sh report.sh") == ""


@pytest.mark.parametrize(
    ("agent", "rel", "handler"),
    [
        ("pi", ".pi/extensions/cairnkit.ts", 'pi.on("tool_call"'),
        ("opencode", ".opencode/plugins/cairnkit.js", '"tool.execute.before"'),
    ],
)
def test_a_generated_adapter_gets_the_reason_as_plain_text(repo, mem, agent, rel, handler):
    assert main(["hooks", "install", "--agent", agent]) == 0
    assert handler in (repo / rel).read_text()
    assert main(["add", FIX]) == 0
    # The generated adapter runs this command with the payload that it builds.
    argv = [sys.executable, "-m", "cairnkit", "hook", "before-shell", "--agent", agent]
    assert run(argv, repo, "sh report.sh").startswith("memory: this call did not run.")
    assert run(argv, repo, "sh report.sh") == ""


@pytest.mark.parametrize(
    ("text", "command", "form"),
    [
        (FIX, "cd /x && sh report.sh 2>&1 | tail -3", "REPORT_LOCALE=C sh report.sh"),
        (f"Run it as '{LONG}'.", "sh report.sh", LONG),
        ("Tests need `uv run pytest -q`.", "pytest -q", "uv run pytest -q"),
        (FIX, "FOO=1 sh report.sh > out.txt", "REPORT_LOCALE=C sh report.sh"),
        ("sh report.sh is slow on Mondays.", "sh report.sh", None),
        ("report.sh needs a locale.", "sh report.sh", None),
        ("Do not run sh report.sh in CI.", "sh report.sh", None),
        (FIX, "sh report", None),
        # A pattern in quotes is no step, whatever it holds.
        ("Run it as DATABASE_URL=x manage.py", "ps ax | grep -E 'check|manage.py'", None),
        ("Run it as DATABASE_URL=x manage.py", "echo 'a;manage.py'", None),
        # One plain word is part of too many commands.
        ("Use `sudo make install`.", "make", None),
        (FIX, "sh report.sh &>/dev/null &", "REPORT_LOCALE=C sh report.sh"),
        (FIX, "sh report.sh.bak", None),
        # The body of a heredoc is text that a command writes, not a step.
        (FIX, "cat <<EOF > notes.md\nsh report.sh\nEOF", None),
        (FIX, "cat <<-'EOF'\n\tsh report.sh\n\tEOF", None),
        (FIX, 'cat <<"A" >x\nsh report.sh\nA\nsh report.sh', "REPORT_LOCALE=C sh report.sh"),
        (FIX, "cat <<EOF\nsh report.sh", None),
        (FIX, "cat <<< 'x'; sh report.sh", "REPORT_LOCALE=C sh report.sh"),
    ],
)
def test_the_match_is_the_same_core_behind_a_prefix(text, command, form):
    found = hits(command, [{"id": "f", "text": text}])
    assert [hit.form for hit in found] == ([form] if form else [])


def test_the_time_budget_holds_through_code_that_catches_errors():
    """A broad `except Exception` inside a hook step must not eat the end of its time."""
    import contextlib
    import time

    from cairnkit.hookrun import _time_budget

    start = time.monotonic()
    with _time_budget(0.2):
        with contextlib.suppress(Exception):
            time.sleep(1)
        time.sleep(3)
    assert time.monotonic() - start < 1


def test_install_stops_no_tool_with_an_allow(repo, mem):
    """An allow would skip the person's own approval of the command. The hook only denies."""
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    group = json.loads((repo / ".claude/settings.local.json").read_text())["hooks"]["PreToolUse"]
    assert group[0]["matcher"] == "Bash"
    assert re.search(r"hook before-shell --agent claude", group[0]["hooks"][0]["command"])


def test_a_new_hook_line_never_stops_a_tool_under_an_older_build(repo, mem):
    """An older build does not know a new event and exits 2, and an exit 2 blocks the tool call.

    The line runs as Claude Code runs it, in a shell, with an event that this build does not know.
    """
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    hooks = json.loads((repo / ".claude/settings.local.json").read_text())["hooks"]
    lines = [
        h["command"]
        for event in ("PreToolUse", "SubagentStop")
        for g in hooks[event]
        for h in g["hooks"]
        if "cairnkit" in h["command"]
    ]
    assert len(lines) == 3
    for line in lines:
        old = re.sub(r"hook \S+ --agent", "hook no-such-event --agent", line)
        done = subprocess.run(
            ["sh", "-c", old], cwd=repo, input="{}", capture_output=True, text=True
        )
        assert done.returncode == 0, (line, done.stderr)
