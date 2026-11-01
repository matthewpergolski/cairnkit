"""A tool found on PATH gets connected with no step. Only real use earns the Codex trust line."""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from conftest import add_worktree, git

from cairnkit import adapters, hooks_cmd
from cairnkit.cli import main
from cairnkit.paths import find_project

TRUST = " /hooks"
TODAY = "2026-11-01T12:00:00+00:00"


@pytest.fixture
def tools(repo, monkeypatch):
    """What `detect` finds. A test changes the list when a tool appears."""
    found = ["claude"]
    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    monkeypatch.setattr(adapters, "detect", lambda project: list(found))
    monkeypatch.setenv("MEMORY_NOW", TODAY)
    return found


def session_start(capsys, agent="claude"):
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", agent]) == 0
    return capsys.readouterr().out


def codex_session(day: str, home=None):
    base = home or os.path.join(os.environ["HOME"], ".codex")
    folder = os.path.join(base, "sessions", *day.split("-"))
    os.makedirs(folder)
    with open(os.path.join(folder, "rollout.jsonl"), "w") as handle:
        handle.write("{}\n")


# --- the Codex trust line -------------------------------------------------------------


def test_the_trust_line_is_silent_when_codex_was_never_used(tools, capsys):
    tools.append("codex")
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "codex" in out and TRUST not in out


def test_the_trust_line_shows_after_any_codex_session(tools, capsys):
    tools.append("codex")
    codex_session("2026-10-20")
    assert main(["init"]) == 0
    assert TRUST in capsys.readouterr().out


def test_a_long_break_does_not_hide_the_trust_line(tools, capsys):
    tools.append("codex")
    codex_session("2020-01-01")
    assert main(["init"]) == 0
    assert TRUST in capsys.readouterr().out


def test_an_empty_codex_home_is_not_use(tools, capsys):
    tools.append("codex")
    os.makedirs(os.path.join(os.environ["HOME"], ".codex", "sessions", "2026", "11", "01"))
    assert main(["init"]) == 0
    assert TRUST not in capsys.readouterr().out


def test_codex_home_moves_with_its_environment_variable(tools, tmp_path, capsys, monkeypatch):
    tools.append("codex")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "elsewhere"))
    codex_session("2026-10-31", str(tmp_path / "elsewhere"))
    assert main(["init"]) == 0
    assert TRUST in capsys.readouterr().out


def test_status_names_the_trust_step_once_codex_is_in_use(tools, capsys):
    tools.append("codex")
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 0
    assert TRUST not in capsys.readouterr().out
    codex_session("2026-10-31")
    assert main(["status"]) == 0
    assert TRUST in capsys.readouterr().out


def test_an_explicit_codex_install_always_names_the_trust_step(tools, capsys):
    assert main(["init"]) == 0
    capsys.readouterr()
    assert main(["hooks", "install", "--agent", "codex"]) == 0
    assert TRUST in capsys.readouterr().out


# --- a tool that appears later --------------------------------------------------------


def test_a_session_start_connects_a_new_tool_and_says_nothing(tools, repo, capsys):
    assert main(["init"]) == 0
    quiet = session_start(capsys)
    tools.append("codex")
    out = session_start(capsys)
    assert "SessionStart" in json.loads((repo / ".codex" / "hooks.json").read_text())["hooks"]
    assert len(out.split()) == len(quiet.split())
    assert git(repo, "status", "--porcelain") == ""


def test_a_tool_on_the_real_path_is_found(repo, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    programs = tmp_path / "programs"
    programs.mkdir()
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}/usr/bin{os.pathsep}/bin")
    (repo / ".claude").mkdir()
    assert main(["init"]) == 0
    assert not (repo / ".opencode" / "plugins" / "cairnkit.js").exists()
    program = programs / "opencode"
    program.write_text("#!/bin/sh\n")
    program.chmod(0o755)
    session_start(capsys)
    assert (repo / ".opencode" / "plugins" / "cairnkit.js").is_file()


def test_a_git_event_connects_a_new_tool_and_prints_nothing(tools, repo, capsys):
    assert main(["init"]) == 0
    tools.append("cursor")
    capsys.readouterr()
    assert main(["hook", "post-merge"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    assert (repo / ".cursor" / "hooks.json").is_file()


def test_a_new_tool_reaches_each_linked_worktree(tools, repo, capsys):
    assert main(["init"]) == 0
    other = add_worktree(repo, "other")
    assert main(["load"]) == 0
    assert main(["hooks", "install", "--agent", "claude"]) == 0  # links the worktree
    tools.append("codex")
    session_start(capsys)
    assert (repo / ".codex" / "hooks.json").is_file()
    assert (other / ".codex" / "hooks.json").is_file()


def test_a_tool_chosen_out_stays_out(tools, repo, capsys):
    tools.append("codex")
    assert main(["init", "--no-hooks"]) == 0
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    session_start(capsys)
    assert not (repo / ".codex" / "hooks.json").exists()


def test_a_removed_adapter_does_not_come_back(tools, repo, capsys):
    tools.append("codex")
    assert main(["init"]) == 0
    (repo / ".codex" / "hooks.json").unlink()
    session_start(capsys)
    assert not (repo / ".codex" / "hooks.json").exists()


def test_a_tracked_adapter_is_never_written(tools, repo, capsys):
    assert main(["init"]) == 0
    path = repo / ".codex" / "hooks.json"
    path.parent.mkdir()
    path.write_text('{"mine": true}\n')
    git(repo, "add", "-f", ".codex/hooks.json")
    git(repo, "commit", "-qm", "track it")
    tools.append("codex")
    session_start(capsys)
    assert path.read_text() == '{"mine": true}\n'
    assert git(repo, "status", "--porcelain") == ""


def test_a_bad_config_never_stops_the_session_and_is_tried_again(tools, repo, capsys):
    assert main(["init"]) == 0
    path = repo / ".codex" / "hooks.json"
    path.parent.mkdir()
    path.write_text("{not json")
    tools.append("codex")
    assert "# Project memory" in session_start(capsys)
    assert path.read_text() == "{not json"
    path.unlink()
    session_start(capsys)
    assert path.is_file()


def test_a_memory_from_before_the_record_connects_new_tools_once(tools, repo, capsys):
    assert main(["init"]) == 0
    (repo.parent / "proj.memory" / hooks_cmd.SEEN_FILE).unlink()
    tools.append("codex")
    session_start(capsys)
    assert (repo / ".codex" / "hooks.json").is_file()


def test_no_connected_tool_and_no_record_means_no_sync(tools, repo, capsys):
    assert main(["init", "--no-hooks"]) == 0
    tools.append("codex")
    session_start(capsys)
    assert not (repo / ".claude" / "settings.local.json").exists()
    assert not (repo / ".codex" / "hooks.json").exists()


def test_grok_stops_when_claude_arrives_so_each_hook_runs_once(repo, capsys, monkeypatch):
    found = ["grok"]
    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    monkeypatch.setattr(adapters, "detect", lambda project: list(found))
    assert main(["init"]) == 0
    assert (repo / ".grok" / "hooks" / "cairnkit.json").is_file()
    found[:] = ["claude"]
    session_start(capsys, "grok")
    assert (repo / ".claude" / "settings.local.json").is_file()
    assert not (repo / ".grok" / "hooks" / "cairnkit.json").exists()


def test_the_quiet_path_runs_no_program(tools, repo, monkeypatch):
    assert main(["init"]) == 0
    project = find_project()

    def no_program(*args, **kwargs):
        raise AssertionError(f"a program ran: {args}")

    monkeypatch.setattr(subprocess, "run", no_program)
    monkeypatch.setattr(subprocess, "Popen", no_program)
    hooks_cmd.connect_new_tools(project, None)
