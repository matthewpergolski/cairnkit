"""The work-landed signal stays cheap: a slow git costs one bounded try, and its cache is safe.

A review saw one unbounded `git log` over 400 paths time out at each session start on a repo of
30,000 commits. It wrote no cache, so each session tried again, and it marked git as stuck, so
the load said that it was partial.
"""

from __future__ import annotations

import io
import json
import os
import shutil

import pytest
from test_landed import add, at, commit, found

from cairnkit import deadline, landed
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project

LANDED_LOG = "--name-status"


def slow_landed_log(tmp_path, monkeypatch) -> object:
    """A git whose landed log hangs. Each call of that log adds a line to the returned file."""
    folder = tmp_path / "slow-bin"
    folder.mkdir()
    calls = tmp_path / "landed-calls"
    fake = folder / "git"
    fake.write_text(
        "#!/bin/sh\n"
        f'case " $* " in *" {LANDED_LOG} "*) echo log >> "{calls}"; exec sleep 30;; esac\n'
        f'exec "{shutil.which("git")}" "$@"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(landed, "GIT_TIMEOUT", 0.3)
    return calls


def landed_calls(calls) -> int:
    return len(calls.read_text().splitlines()) if calls.exists() else 0


def approval(capsys, monkeypatch, repo) -> str:
    at(monkeypatch, "10")
    fid = add(capsys, "Yes to the app split.", "--kind", "decision", "--files", "src/app.py")
    at(monkeypatch, "11")
    commit(repo, "app", {"src/app.py": "v1\n"})
    return fid


def hook(capsys, monkeypatch, event, **payload) -> str:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s", **payload})))
    capsys.readouterr()
    main(["hook", event, "--agent", "claude"])
    return capsys.readouterr().out


def test_a_timeout_is_kept_and_does_not_mark_git_stuck(mem, repo, capsys, monkeypatch, tmp_path):
    approval(capsys, monkeypatch, repo)
    calls = slow_landed_log(tmp_path, monkeypatch)
    memory = Memory.open(find_project(repo), None)
    with deadline.within(7):
        cuts = deadline.git_cuts()
        assert landed.find(memory) == {}
        assert not deadline.git_stuck(), "the hook's own git still runs"
        assert deadline.git_cuts() == cuts, "the load is not partial"
    assert landed_calls(calls) == 1
    cache = json.loads((mem / landed.CACHE_NAME).read_text())
    assert set(cache["facts"].values()) == {landed.UNKNOWN}
    with deadline.within(7):
        assert landed.find(Memory.open(find_project(repo), None)) == {}
    assert landed_calls(calls) == 1, "the next hook does not ask again"


def test_tidy_asks_again_after_a_timeout(mem, repo, capsys, monkeypatch, tmp_path):
    fid = approval(capsys, monkeypatch, repo)
    calls = slow_landed_log(tmp_path, monkeypatch)
    with deadline.within(7):
        landed.find(Memory.open(find_project(repo), None))
    monkeypatch.setenv("PATH", os.environ["PATH"].split(os.pathsep, 1)[1])
    capsys.readouterr()
    assert main(["tidy"]) == 0
    assert f"[landed] {fid}" in capsys.readouterr().out
    assert landed_calls(calls) == 1


def test_a_slow_landed_log_leaves_the_session_start_whole(mem, repo, capsys, monkeypatch, tmp_path):
    approval(capsys, monkeypatch, repo)
    slow_landed_log(tmp_path, monkeypatch)
    out = hook(capsys, monkeypatch, "session-start", source="startup")
    assert "# Project memory" in out
    assert "partial" not in out


def test_the_prompt_and_shell_hooks_run_no_landed_log(mem, repo, capsys, monkeypatch, tmp_path):
    approval(capsys, monkeypatch, repo)
    hook(capsys, monkeypatch, "session-start", source="startup")
    (mem / landed.CACHE_NAME).unlink()
    state_path = mem / ".sessions" / "s.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["shown"] = []
    state_path.write_text(json.dumps(state), encoding="utf-8")
    calls = slow_landed_log(tmp_path, monkeypatch)
    (repo / "src" / "app.py").write_text("v2\n")
    hook(capsys, monkeypatch, "prompt", prompt="go on")
    hook(capsys, monkeypatch, "after-shell", tool_name="Bash", tool_input={"command": "ls"})
    assert landed_calls(calls) == 0


def test_the_paths_are_capped_newest_first(mem, repo, capsys, monkeypatch):
    monkeypatch.setattr(landed, "MAX_PATHS", 3)
    at(monkeypatch, "05")
    ids = []
    for n in range(4):
        at(monkeypatch, f"0{n + 5}")
        ids.append(add(capsys, f"Yes to part {n}.", "--kind", "decision", "--files", f"p{n}.py"))
    at(monkeypatch, "12")
    commit(repo, "parts", {f"p{n}.py": "x\n" for n in range(4)})
    assert set(found(repo)) == set(ids[1:]), "the oldest waits"


def test_the_walk_is_bounded(mem, repo, capsys, monkeypatch):
    monkeypatch.setattr(landed, "MAX_COMMITS", 3)
    fid = approval(capsys, monkeypatch, repo)
    for n in range(3):
        commit(repo, f"other {n}", {f"other{n}.py": "x\n"})
    assert fid not in found(repo), "the commit is past the bound, so the answer waits"


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[]",
        '{"tips": "x", "facts": []}',
        '{"version": 1, "tips": [], "facts": {}}',
        '{"version": 2, "tips": [], "facts": {"k": 5}}',
    ],
)
def test_a_bad_cache_is_read_again_from_git(mem, repo, capsys, monkeypatch, body):
    fid = approval(capsys, monkeypatch, repo)
    (mem / landed.CACHE_NAME).write_text(body)
    assert fid in found(repo)
    cache = json.loads((mem / landed.CACHE_NAME).read_text())
    assert cache["version"] == landed.CACHE_VERSION


@pytest.mark.parametrize("entry", [5, ["one"], [1, 2, 3], {"commit": "x"}, "maybe"])
def test_a_bad_entry_is_ignored(mem, repo, capsys, monkeypatch, entry):
    fid = approval(capsys, monkeypatch, repo)
    assert fid in found(repo)
    path = mem / landed.CACHE_NAME
    cache = json.loads(path.read_text())
    cache["facts"] = {key: entry for key in cache["facts"]}
    path.write_text(json.dumps(cache))
    assert fid in found(repo)


def test_the_cache_is_written_whole(mem, repo, capsys, monkeypatch):
    approval(capsys, monkeypatch, repo)
    found(repo)
    leftovers = [
        p.name for p in mem.iterdir() if p.name.startswith(".landed") and p.suffix == ".tmp"
    ]
    assert leftovers == []
    assert json.loads((mem / landed.CACHE_NAME).read_text())["version"] == landed.CACHE_VERSION
