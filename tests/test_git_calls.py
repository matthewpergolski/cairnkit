"""The hooks run no more git than before the check of who put a memory pointer.

Each git call costs a hook about 10 ms, and a tool call waits for the shell hook. The counts
below are the counts of 0.3.1-dev before that check (commit 6b4bdf0), in the same setup. A rise
fails here. An outer repo, such as a home folder that is a git repo, must add no call.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest
from conftest import add_worktree, git

SESSION = json.dumps({"session_id": "t", "source": "startup"})
SHELL = json.dumps({"session_id": "t", "tool_name": "Bash", "tool_input": {"command": "ls"}})
PROMPT = json.dumps({"session_id": "t", "prompt": "hello"})


def _tool(repo, env, *args, stdin=""):
    return subprocess.run(
        [sys.executable, "-P", "-m", "cairnkit", *args],
        cwd=repo,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )


def _counting_env(tmp_path):
    folder = tmp_path / "count-bin"
    folder.mkdir()
    log = tmp_path / "git-calls.log"
    fake = folder / "git"
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexec "{shutil.which("git")}" "$@"\n')
    fake.chmod(0o755)
    return {**os.environ, "PATH": f"{folder}{os.pathsep}{os.environ['PATH']}"}, log


def _calls(repo, env, log, event, stdin) -> list[str]:
    log.write_text("")
    _tool(repo, env, "hook", event, "--agent", "claude", stdin=stdin)
    return log.read_text().splitlines()


@pytest.mark.parametrize(
    ("checkouts", "outer", "start_budget"),
    [(0, False, 57), (10, False, 67), (0, True, 57)],
    ids=["one-checkout", "ten-checkouts", "outer-repo"],
)
def test_the_hooks_run_no_more_git_than_before(repo, tmp_path, checkouts, outer, start_budget):
    if outer:
        git(tmp_path, "init", "-q")
    _tool(repo, os.environ, "init", "--no-default-rules")
    for n in range(checkouts):
        add_worktree(repo, f"wt{n}")
    env, log = _counting_env(tmp_path)
    _tool(repo, env, "hook", "session-start", "--agent", "claude", stdin=SESSION)
    start = _calls(repo, env, log, "session-start", SESSION)
    shell = _calls(repo, env, log, "before-shell", SHELL)
    prompt = _calls(repo, env, log, "prompt", PROMPT)
    assert len(shell) <= 3, shell
    assert len(prompt) <= 11, prompt
    assert len(start) <= start_budget, start
