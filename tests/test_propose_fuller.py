"""pre-push / post-merge fuller propose, and stop fallback when no commit."""

from __future__ import annotations

import io
import json

from conftest import git

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.session import load_state, start_session


def install(capsys):
    capsys.readouterr()
    assert main(["hooks", "install", "--agent", "generic"]) == 0


def pending_rows(mem):
    path = mem / "proposals" / "auto-candidates.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def candidates(mem):
    return [r for r in pending_rows(mem) if r.get("type", "candidate") == "candidate"]


def test_pre_push_fuller_prefers_lessons_and_skips_near_active(repo, mem, capsys):
    install(capsys)
    # An active fact that matches one commit message near-exactly.
    from conftest import make_fact, write_facts

    write_facts(
        mem,
        [make_fact("f-20261001-0001", "Deploy only from a clean tree after tests pass.")],
    )
    # Drop post-commit so draft+gate do not pre-accept before the fuller pass.
    post = repo / ".git" / "hooks" / "post-commit"
    if post.exists():
        post.unlink()
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "lesson: always pin the lockfile before release")
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "b.txt")
    # Near-dup of the active fact: fuller must skip it.
    git(repo, "commit", "-q", "-m", "lesson: deploy only from a clean tree after tests pass")
    path = mem / "proposals" / "auto-candidates.jsonl"
    if path.exists():
        path.write_text("")
    capsys.readouterr()
    assert main(["hook", "pre-push"]) == 0
    found = candidates(mem)
    texts = " ".join(c["text"].lower() for c in found)
    assert "pin the lockfile" in texts or "lockfile" in texts
    assert all("clean tree after tests" not in c["text"].lower() for c in found)
    assert all(c.get("origin") == "fuller" for c in found)


def test_post_merge_runs_fuller_propose(repo, mem, capsys):
    install(capsys)
    (repo / "m.txt").write_text("m\n")
    git(repo, "add", "m.txt")
    git(repo, "commit", "-q", "-m", "decision: use the CDN for static fonts")
    path = mem / "proposals" / "auto-candidates.jsonl"
    if path.exists():
        path.write_text("")
    capsys.readouterr()
    assert main(["hook", "post-merge"]) == 0
    found = candidates(mem)
    assert found
    assert any(c["kind"] == "decision" for c in found)
    assert all(c.get("origin") == "fuller" for c in found)


def test_stop_fallback_when_session_made_no_commit(repo, mem, capsys, monkeypatch):
    install(capsys)
    memory = Memory.open(find_project(), None)
    start_session(memory, "sess-1")
    state = load_state(memory, "sess-1")
    assert state and state.get("start_head")
    # Dirty durable file, same HEAD as session start.
    (repo / "work.py").write_text("print('hi')\n")
    path = mem / "proposals" / "auto-candidates.jsonl"
    if path.exists():
        path.unlink()
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "sess-1"}'))
    capsys.readouterr()
    # cursor stop always exits 0 (JSON followup); generic would exit 1 on a reminder.
    assert main(["hook", "stop", "--agent", "cursor"]) == 0
    found = candidates(mem)
    assert found, "stop fallback must draft when HEAD is unchanged"
    assert all(c.get("origin") == "stop_fallback" for c in found)


def test_stop_skips_fallback_after_a_commit(repo, mem, capsys, monkeypatch):
    install(capsys)
    memory = Memory.open(find_project(), None)
    start_session(memory, "sess-2")
    (repo / "done.txt").write_text("x\n")
    git(repo, "add", "done.txt")
    git(repo, "commit", "-q", "-m", "chore: session commit")
    path = mem / "proposals" / "auto-candidates.jsonl"
    if path.exists():
        path.write_text("")
    (repo / "extra.py").write_text("x = 1\n")
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "sess-2"}'))
    capsys.readouterr()
    assert main(["hook", "stop", "--agent", "cursor"]) == 0
    found = [c for c in candidates(mem) if c.get("origin") == "stop_fallback"]
    assert found == []
