"""A session start fits its budget and still prints the facts. A lock wait has a limit."""

from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time

import pytest
from conftest import git, make_fact, read_jsonl, write_facts

from cairnkit import deadline, store
from cairnkit.cli import main
from cairnkit.paths import find_project, run_git

PINNED = "f-20261001-0001"
SHORT = "f-20261001-0002"
FLAGS = ["--basis", "seen", "--source", "session:2026-11-01"]
TOOL_TIMEOUT = 10


def _slow_git(tmp_path, seconds):
    folder = tmp_path / "slow-bin"
    folder.mkdir()
    fake = folder / "git"
    fake.write_text(f'#!/bin/sh\nsleep {seconds}\nexec "{shutil.which("git")}" "$@"\n')
    fake.chmod(0o755)
    return {**os.environ, "PATH": f"{folder}{os.pathsep}{os.environ['PATH']}"}


def _command(repo, env, *args, stdin="{}"):
    begun = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-m", "cairnkit", *args],
        cwd=repo,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return done, time.monotonic() - begun


def _seed(mem):
    (mem / "config.toml").write_text('auto_tidy = "on"\n')
    write_facts(mem, [make_fact(PINNED, "Pinned trap about the webhook.", pinned=True)])
    write_facts(
        mem,
        [
            make_fact(
                f"f-20261001-1{i:03x}",
                f"Note {i} until an old branch.",
                scope="short",
                until_branch_merged=f"oldbranch{i}",
            )
            for i in range(5)
        ],
    )


@pytest.mark.parametrize("seconds", [2, 600])
@pytest.mark.parametrize(
    "args", [["hook", "session-start", "--agent", "claude"], ["load"]], ids=["hook", "load"]
)
def test_slow_or_hung_git_stays_in_budget_and_prints_the_facts(mem, repo, tmp_path, seconds, args):
    _seed(mem)
    done, took = _command(repo, _slow_git(tmp_path, seconds), *args)
    assert done.returncode == 0
    assert "Pinned trap about the webhook." in done.stdout
    assert took < TOOL_TIMEOUT


def test_a_slow_git_ends_no_fact(mem, repo, tmp_path):
    _seed(mem)
    _command(repo, _slow_git(tmp_path, 2), "hook", "session-start", "--agent", "claude")
    changes = [r for r in read_jsonl_all(mem) if r.get("type") == "change" and r.get("status")]
    assert changes == []


def read_jsonl_all(mem):
    return [r for path in (mem / "facts").glob("*.jsonl") for r in read_jsonl(path)]


def test_add_with_a_slow_git_lands_soon(mem, repo, tmp_path):
    _seed(mem)
    text = "A fact added while git is slow."
    done, took = _command(repo, _slow_git(tmp_path, 2), "add", text, *FLAGS)
    assert done.returncode == 0
    assert text in (mem / "facts" / "main.jsonl").read_text()
    assert took < 30


def test_a_held_tidy_lock_does_not_stop_a_session(mem, repo):
    _seed(mem)
    with (mem / ".auto-tidy.lock").open("ab") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        done, took = _command(repo, os.environ, "hook", "session-start", "--agent", "claude")
    assert done.returncode == 0
    assert "Pinned trap about the webhook." in done.stdout
    assert took < TOOL_TIMEOUT


def test_a_held_fact_lock_makes_add_fail_clearly_and_a_retry_lands(mem, repo):
    write_facts(mem, [make_fact(PINNED, "Something.")])
    text = "A fact written while the file is locked."
    path = mem / "facts" / "main.jsonl"
    with (mem / "facts" / store.WRITE_LOCK).open("ab") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        done, took = _command(repo, os.environ, "add", text, *FLAGS)
    assert done.returncode == 1
    assert "Nothing was written" in done.stderr
    assert "added" not in done.stdout
    assert took < 8
    assert text not in path.read_text()
    done, _ = _command(repo, os.environ, "add", text, *FLAGS)
    assert done.returncode == 0
    assert text in path.read_text()


def test_a_lock_wait_ends_with_a_clear_result(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "LOCK_WAIT", 0.1)
    lock = tmp_path / ".lock"
    with lock.open("ab") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(store.LockBusy, match="Nothing was written"), store.locked(lock):
            pytest.fail("the block must not run")
    with store.locked(lock):
        pass


def test_a_lock_wait_stays_inside_the_budget(tmp_path):
    lock = tmp_path / ".lock"
    with lock.open("ab") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        begun = time.monotonic()
        with deadline.within(0.1), pytest.raises(store.LockBusy), store.locked(lock):
            pytest.fail("the block must not run")
    assert time.monotonic() - begun < 2


def test_git_past_the_budget_runs_nothing(repo):
    assert run_git(repo, "rev-parse", "HEAD")
    with deadline.within(0):
        assert run_git(repo, "rev-parse", "HEAD") is None
    assert run_git(repo, "rev-parse", "HEAD")


def test_budgets_nest_and_end(repo):
    assert deadline.left() == float("inf")
    with deadline.within(100):
        with deadline.within(1000):
            assert deadline.left() <= 100
        with deadline.within(1):
            assert deadline.left() <= 1
        assert 1 < deadline.left() <= 100
    assert deadline.left() == float("inf")


def test_the_update_check_git_stays_inside_the_budget():
    from cairnkit import install_source

    with deadline.within(0):
        begun = time.monotonic()
        assert install_source.git(["--version"]) is None
    assert time.monotonic() - begun < 1
    assert install_source.git(["--version"])


def test_a_timed_out_git_is_not_called_again_in_the_budget(repo, tmp_path, monkeypatch):
    env = _slow_git(tmp_path, 600)
    monkeypatch.setenv("PATH", env["PATH"])
    begun = time.monotonic()
    with deadline.within(100):
        assert run_git(repo, "status", timeout=0.2) is None
        assert not deadline.has_time()
        assert run_git(repo, "status", timeout=30) is None
    assert time.monotonic() - begun < 5


def test_a_failed_git_keeps_the_end_of_no_note(mem, repo, tmp_path, monkeypatch, capsys):
    """A branch that git cannot read stays open. A timeout is not evidence of a merge."""
    git(repo, "switch", "-qc", "gone")
    git(repo, "commit", "-q", "--allow-empty", "-m", "x")
    tip = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "switch", "-q", "main")
    git(repo, "branch", "-qD", "gone")
    write_facts(
        mem,
        [
            make_fact(
                SHORT,
                "A note until gone.",
                scope="short",
                until_branch_merged="gone",
                branch_tip=tip,
            )
        ],
    )
    monkeypatch.setenv("PATH", _slow_git(tmp_path, 600)["PATH"])
    with deadline.within(0):
        from cairnkit.paths import merged_checker

        assert merged_checker(repo)("gone", tip) is False


def test_a_tracked_file_is_not_written_when_git_cannot_say(repo):
    from cairnkit.ignore import is_tracked

    project = find_project(repo)
    with deadline.within(0):
        assert is_tracked(project, "README.md") is True


def test_a_gone_held_by_is_not_reported_when_git_cannot_say(mem, repo, capsys):
    from cairnkit.check import check_records
    from cairnkit.memory import Memory

    write_facts(
        mem,
        [
            make_fact(PINNED, "Held."),
            {
                "type": "change",
                "id": PINNED,
                "at": "2026-10-02T12:00:00+00:00",
                "status": "promoted",
                "held_by": "docs/not-here.md",
                "reason": "r",
                "writer": "main",
            },
        ],
    )
    memory = Memory.open(find_project(), None)
    with deadline.within(0):
        errors, _ = check_records(memory)
    assert not [e for e in errors if "held_by" in e]


def test_an_open_stdin_does_not_stop_a_session(mem, repo):
    _seed(mem)
    begun = time.monotonic()
    process = subprocess.Popen(
        [sys.executable, "-m", "cairnkit", "hook", "session-start", "--agent", "claude"],
        cwd=repo,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.read().count("Pinned trap about the webhook.") >= 1
        process.wait(timeout=30)
    finally:
        process.kill()
    assert time.monotonic() - begun < TOOL_TIMEOUT


def _timeouts_in(value, found):
    if isinstance(value, dict):
        command, limit = value.get("command"), value.get("timeout")
        event = re.search(r"\bhook ([a-z-]+)", command) if isinstance(command, str) else None
        if event and limit:
            found.append((event.group(1), limit))
        for item in value.values():
            _timeouts_in(item, found)
    elif isinstance(value, list):
        for item in value:
            _timeouts_in(item, found)


def test_each_budget_is_under_the_shortest_timeout_of_each_adapter(repo, mem, capsys):
    for agent in ("claude", "codex", "cursor", "grok", "pi", "opencode"):
        assert main(["hooks", "install", "--agent", agent]) == 0
    found: list = []
    for rel in (
        ".claude/settings.local.json",
        ".codex/hooks.json",
        ".cursor/hooks.json",
        ".grok/hooks/cairnkit.json",
    ):
        _timeouts_in(json.loads((repo / rel).read_text()), found)
    events = {event for event, _ in found}
    assert {"session-start", "stop", "after-shell", "prompt", "subagent-start"} <= events
    for event, limit in found:
        assert deadline.COMMAND_BUDGET[event] < limit, event
    shortest = min(limit for _, limit in found)
    for command in ("add", "change", "keep", "purge"):
        assert deadline.COMMAND_BUDGET[command] + store.WRITE_LOCK_FLOOR < shortest
    for rel in (".pi/extensions/cairnkit.ts", ".opencode/plugins/cairnkit.js"):
        millis = {int(m) for m in re.findall(r"timeout: (\d+)", (repo / rel).read_text())}
        assert max(deadline.COMMAND_BUDGET.values()) * 1000 < min(millis)
