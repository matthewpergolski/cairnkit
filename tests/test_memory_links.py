"""A hook or a command changes nothing outside the memory folder through a link inside it.

A link in the memory folder can come from a repo: a `.memory-path` or a `memory-bank` link can
name a folder in the checkout, and git keeps links. Each write, delete, prune and walk under the
memory folder stops at a link.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_odd_files import SWEEP

from cairnkit.cli import main


def aged(path: Path, seconds: float) -> Path:
    past = time.time() - seconds
    os.utime(path, (past, past), follow_symlinks=False)
    return path


def tree(folder: Path) -> dict[str, tuple[bytes, int]]:
    return {
        p.relative_to(folder).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in folder.rglob("*")
        if p.is_file()
    }


def hook(monkeypatch, event: str, payload: dict) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    return main(["hook", event, "--agent", "claude"])


@pytest.fixture
def outside(tmp_path) -> Path:
    folder = tmp_path / "outside"
    folder.mkdir()
    return folder


def test_session_start_prunes_and_writes_nothing_through_a_sessions_link(
    repo, mem, outside, monkeypatch
):
    (outside / "old.json").write_text("{}")
    aged(outside / "old.json", 8 * 86400)
    (outside / "recent.json").write_text("{}")
    before = tree(outside)
    (mem / ".sessions").symlink_to(outside)
    assert hook(monkeypatch, "session-start", {"session_id": "s1", "source": "startup"}) == 0
    assert tree(outside) == before


def test_session_start_removes_nothing_through_a_live_link(repo, mem, outside, monkeypatch):
    (outside / "keep.txt").write_text("keep\n")
    aged(outside / "keep.txt", 3600)
    before = tree(outside)
    (mem / ".sessions").mkdir(exist_ok=True)
    (mem / ".sessions" / "live").symlink_to(outside)
    assert hook(monkeypatch, "session-start", {"session_id": "s1", "source": "startup"}) == 0
    assert tree(outside) == before


def test_after_shell_writes_nothing_through_a_state_link(repo, mem, outside, monkeypatch):
    kept = outside / "kept.txt"
    kept.write_text("keep\n")
    (mem / ".loop-breaker.json").symlink_to(kept)
    payload = {
        "session_id": "s1",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
        "tool_response": {},
    }
    assert hook(monkeypatch, "after-shell", payload) == 0
    assert kept.read_text() == "keep\n"


def test_add_makes_no_lock_file_through_a_dangling_link(repo, mem, outside, capsys):
    (mem / "facts" / ".write.lock").unlink(missing_ok=True)
    (mem / "facts" / ".write.lock").symlink_to(outside / "made.lock")
    main(["add", "We chose uv over pip for installs."])
    assert list(outside.iterdir()) == []


def test_migrate_removes_nothing_through_a_linked_folder(repo, mem, outside, capsys):
    (outside / "dummy.md").write_text("victim text\n")
    (mem / "archive").symlink_to(outside)
    main(["migrate", "--yes"])
    assert (outside / "dummy.md").read_text() == "victim text\n"


def test_migrate_creates_nothing_through_a_dangling_link(repo, mem, outside, capsys):
    (mem / "plan.md").write_text("plan text\n")
    (mem / "notes" / "plan.md").unlink(missing_ok=True)
    (mem / "notes" / "plan.md").symlink_to(outside / "created.txt")
    main(["migrate", "--yes"])
    assert list(outside.iterdir()) == []


LINK_SWEEP = {
    **SWEEP,
    "hook after-shell": (
        ("hook", "after-shell", "--agent", "claude"),
        {
            "session_id": "s1",
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
            "tool_response": {},
        },
    ),
}


# Writes that once followed a link. The sweep must reach them.
WRITES_REACHED = {
    "hook session-start": [".sessions/s1.json", ".auto-tidy.lock"],
    "hook after-shell": [".loop-breaker.json"],
    "add": ["facts/main.jsonl", "facts/.write.lock"],
}


@pytest.mark.parametrize("name", LINK_SWEEP)
def test_no_write_of_a_command_leaves_the_memory_folder_through_a_link(
    mem: Path, repo: Path, tmp_path: Path, name: str
):
    """Each file in the memory folder that the command writes, makes or removes, and each folder
    above it, is a link to a copy outside in turn. The sweep finds the files itself, so a new
    write is in it."""
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    assert main(["add", "We chose uv over pip for installs."]) == 0
    args, payload = LINK_SWEEP[name]
    work = tmp_path / "sweep"
    work.mkdir()
    plan = {
        "root": str(repo),
        "memdir": str(mem),
        "args": list(args),
        "stdin": json.dumps(payload) if payload else "",
        "timeout": 10,
        "links": True,
    }
    (work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    driver = Path(__file__).with_name("odd_file_sweep.py")
    subprocess.run(
        [sys.executable, str(driver), str(work / "plan.json"), str(work / "result.json")],
        check=True,
        timeout=900,
    )
    result = json.loads((work / "result.json").read_text(encoding="utf-8"))
    written = {Path(p).relative_to(mem.resolve()).as_posix() for p in result["written"]}
    assert set(WRITES_REACHED.get(name, [])) <= written
    assert result["problems"] == {}
