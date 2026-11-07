"""Git runs only in this project's checkouts, whatever folder a helper record names.

A folder can hold a git config that names a command to run, such as `core.fsmonitor`. The
checkouts that `git worktree list` gives are the project's own. A helper record or a hook payload
is not.
"""

from __future__ import annotations

import io
import json
import subprocess

from conftest import add_worktree

from cairnkit import helpers
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project


def planted_git(folder, marker):
    """A folder that git reads as a repo whose config runs a command at each status."""
    script = marker.parent / "fsmonitor.sh"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    script.chmod(0o755)
    (folder / "objects").mkdir(parents=True)
    (folder / "refs").mkdir()
    (folder / "HEAD").write_text("ref: refs/heads/main\n")
    (folder / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tworktree = ..\n"
        f"\tfsmonitor = {script}\n"
    )
    return folder


def record(mem, checkout, **extra):
    row = {
        "call": "c1",
        "session": "x",
        "kind": "",
        "about": "a helper",
        "task": "",
        "started_at": 1,
        "agent": "h1",
        "checkout": str(checkout),
        "base": "HEAD",
        **extra,
    }
    folder = mem / ".sessions" / "helpers"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "open.json").write_text(json.dumps([row]))


def test_the_planted_folder_runs_its_command_under_git(repo, tmp_path):
    marker = tmp_path / "MARKER"
    evil = planted_git(repo / "evil", marker)
    subprocess.run(["git", "status"], cwd=evil, capture_output=True, timeout=30)
    assert marker.exists(), "this git does not run core.fsmonitor here, so the test shows nothing"


def test_the_load_runs_no_git_in_a_folder_that_is_no_checkout(repo, mem, tmp_path, capsys):
    marker = tmp_path / "MARKER"
    record(mem, planted_git(repo / "evil", marker))
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "a helper" in out and "that folder is no checkout of this project" in out
    assert not marker.exists()


def test_the_load_still_reads_a_helper_worktree(repo, mem, capsys):
    tree = add_worktree(repo, "helper")
    (tree / "work.txt").write_text("x\n")
    record(mem, tree)
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "a helper" in out and "uncommitted work.txt" in out


def test_a_helper_start_runs_no_git_in_a_folder_that_is_no_checkout(
    repo, mem, tmp_path, monkeypatch
):
    marker = tmp_path / "MARKER"
    evil = planted_git(repo / "evil", marker)
    tree = add_worktree(repo, "real")
    memory = Memory.open(find_project(), None)
    for call in ("c1", "c2"):
        payload = {"tool_name": "Agent", "tool_use_id": call, "tool_input": {"description": call}}
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s", **payload})))
        assert main(["hook", "helper-call", "--agent", "claude"]) == 0
    helpers.on_start(memory, "s", {"agent_id": "h1", "cwd": str(evil)})
    assert not marker.exists()
    helpers.on_start(memory, "s", {"agent_id": "h2", "cwd": str(tree)})
    started = {h.agent: h for h in helpers.shown(memory, None)}
    assert started["h1"].checkout is None
    assert started["h2"].checkout == str(tree) and started["h2"].base
