"""A helper's work in its own worktree is work of the session that started it.

Claude Code runs a helper with `isolation: "worktree"` in `.claude/worktrees/agent-<id>`, on branch
`worktree-agent-<id>`. Its hooks run there, with the session key of its parent and an `agent_id`.
The tests drive the hooks that `memory hooks install` wrote, as the tool runs them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import pytest
from conftest import git

from cairnkit.cli import main
from cairnkit.session import WORK_CHANGED, WORK_GAP

EVENTS = {
    "session-start": "SessionStart",
    "prompt": "UserPromptSubmit",
    "after-shell": "PostToolUse",
    "stop": "Stop",
}
STOP_TIMEOUT = 30


class Hooks:
    """The installed Claude Code hooks of one repo, run as the tool runs them."""

    def __init__(self, repo, env=None):
        groups = json.loads((repo / ".claude/settings.local.json").read_text())["hooks"]
        self.argv = {
            name: [
                "sh",
                "-c",
                next(
                    h["command"]
                    for g in groups[event]
                    for h in g["hooks"]
                    if "cairnkit" in h["command"]
                ),
            ]
            for name, event in EVENTS.items()
        }
        self.env = env

    def run(self, event, cwd, session="s1", **payload):
        data = {"session_id": session, "hook_event_name": EVENTS[event], "cwd": str(cwd), **payload}
        done = subprocess.run(
            self.argv[event],
            cwd=cwd,
            input=json.dumps(data),
            capture_output=True,
            text=True,
            timeout=60,
            env=self.env,
        )
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    def block(self, cwd, session="s1", **payload):
        out = self.run("stop", cwd, session, **payload)
        if not out:
            return None
        data = json.loads(out)
        return data.get("reason") if data.get("decision") == "block" else None

    def tool(self, cwd, session="s1", agent=None, command="git status"):
        extra = {"agent_id": agent} if agent else {}
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, **extra}
        self.run("after-shell", cwd, session, tool_response={"exit_code": 0}, **payload)


@pytest.fixture
def hooks(repo, mem):
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    made = Hooks(repo)
    made.run("session-start", repo, source="startup")
    return made


def helper_worktree(repo, name="agent-a1"):
    path = repo / ".claude" / "worktrees" / name
    git(repo, "worktree", "add", "-q", "-b", f"worktree-{name}", str(path))
    return path


def helper_commits(path, text="def parse(): pass\n"):
    (path / "parser.py").write_text(text)
    git(path, "add", "parser.py")
    git(path, "commit", "-qm", "add parser")


def mine(session, path, repo, hooks):
    """One helper of `session` works in `path`: a tool call, then a commit."""
    hooks.tool(path, session, agent="helper-1")
    helper_commits(path)
    hooks.tool(path, session, agent="helper-1", command='git commit -am "add parser"')
    assert hooks.block(path, session, agent_id="helper-1") is None


def test_a_helper_commit_in_its_worktree_blocks_the_main_stop_once(repo, hooks):
    hooks.run("prompt", repo, prompt="have a helper add the parser in a worktree")
    mine("s1", helper_worktree(repo), repo, hooks)
    said = hooks.block(repo)
    assert said and WORK_CHANGED in said
    assert hooks.block(repo, stop_hook_active=True) is None
    hooks.run("prompt", repo, prompt="thanks")
    assert hooks.block(repo) is None


def test_uncommitted_helper_work_blocks_too(repo, hooks):
    hooks.run("prompt", repo, prompt="have a helper start the parser")
    helper = helper_worktree(repo)
    hooks.tool(helper, agent="helper-1")
    (helper / "parser.py").write_text("def parse(): pass\n")
    said = hooks.block(repo)
    assert said and WORK_CHANGED in said


def test_a_helper_that_finishes_after_the_main_stop_blocks_the_next_stop(repo, hooks):
    hooks.run("prompt", repo, prompt="start a helper in the background")
    helper = helper_worktree(repo)
    hooks.tool(helper, agent="helper-1")
    assert hooks.block(repo) is None
    helper_commits(helper)
    hooks.tool(helper, agent="helper-1", command='git commit -am "add parser"')
    hooks.run("prompt", repo, prompt="<task-notification>helper done</task-notification>")
    said = hooks.block(repo)
    assert said and WORK_CHANGED in said


def test_a_helper_that_changed_nothing_does_not_block(repo, hooks):
    hooks.run("prompt", repo, prompt="have a helper read the parser")
    hooks.tool(helper_worktree(repo), agent="helper-1", command="cat README.md")
    assert hooks.block(repo) is None


def test_work_of_another_sessions_helper_does_not_block_this_session(repo, hooks):
    hooks.run("session-start", repo, session="s2", source="startup")
    hooks.run("prompt", repo, prompt="what does the config loader read")
    mine("s2", helper_worktree(repo), repo, hooks)
    assert hooks.block(repo) is None
    said = hooks.block(repo, session="s2")
    assert said and WORK_CHANGED in said


def test_more_helper_work_after_a_decline_waits_for_a_fact_and_the_gap(repo, hooks):
    hooks.run("prompt", repo, prompt="have a helper add the parser")
    helper = helper_worktree(repo)
    mine("s1", helper, repo, hooks)
    assert hooks.block(repo)

    def turn(number):
        hooks.run("prompt", repo, prompt="have the helper go on")
        (helper / "parser.py").write_text(f"def parse(): return {number}\n")
        hooks.tool(helper, agent="helper-1")
        return hooks.block(repo)

    assert [number for number in range(2, 4) if turn(number)] == []
    assert main(["add", "The parser must accept empty input: the importer sends it."]) == 0
    assert [number for number in range(4, WORK_GAP + 6) if turn(number)] == [WORK_GAP + 4]


def test_a_removed_helper_worktree_does_not_block_or_fail(repo, hooks):
    hooks.run("prompt", repo, prompt="have a helper add the parser")
    helper = helper_worktree(repo)
    mine("s1", helper, repo, hooks)
    git(repo, "worktree", "remove", "--force", str(helper))
    assert hooks.block(repo) is None


def test_a_stale_marker_of_this_session_does_not_block_or_fail(repo, mem, hooks, tmp_path):
    hooks.run("prompt", repo, prompt="go on")
    helper = helper_worktree(repo)
    hooks.tool(helper, agent="helper-1")
    shutil.rmtree(helper)
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    git(elsewhere, "init", "-q", "-b", "main")
    (elsewhere / "x.py").write_text("x = 1\n")
    for marker in (mem / ".sessions" / "live").iterdir():
        if str(helper) in marker.read_text():
            (marker.parent / f"{marker.name.split('-')[0]}-0000000000000000").write_text(
                str(elsewhere)
            )
    assert hooks.block(repo) is None


def test_hung_git_in_helper_worktrees_stays_inside_the_stop_timeout(repo, hooks, tmp_path):
    hooks.run("prompt", repo, prompt="have helpers add parsers")
    for number in range(4):
        hooks.tool(helper_worktree(repo, f"agent-a{number}"), agent=f"helper-{number}")
    folder = tmp_path / "slow-bin"
    folder.mkdir()
    real = shutil.which("git")
    (folder / "git").write_text(
        f'#!/bin/sh\ncase "$(pwd)" in *worktrees*) sleep 600;; esac\nexec "{real}" "$@"\n'
    )
    (folder / "git").chmod(0o755)
    slow = Hooks(repo, {**os.environ, "PATH": f"{folder}{os.pathsep}{os.environ['PATH']}"})
    begun = time.monotonic()
    slow.block(repo)
    assert time.monotonic() - begun < STOP_TIMEOUT


def test_no_tracked_file_changes_in_either_checkout(repo, hooks):
    hooks.run("prompt", repo, prompt="have a helper add the parser")
    helper = helper_worktree(repo)
    mine("s1", helper, repo, hooks)
    hooks.block(repo)
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert git(helper, "status", "--porcelain", "--untracked-files=no") == ""
