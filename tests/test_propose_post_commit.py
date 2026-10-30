"""post-commit drafts pending candidates from the just-made commit.

Pending candidates are not facts. They live under proposals/ and never enter
memory load until accepted through the normal add path.
"""

from __future__ import annotations

import json
import subprocess
import time

from conftest import git

from cairnkit import githook
from cairnkit.cli import main


def install(capsys, *args):
    capsys.readouterr()
    code = main(["hooks", "install", *args])
    return code, capsys.readouterr().out


def hook(repo, name):
    return repo / ".git" / "hooks" / name


def pending_path(mem):
    return mem / "proposals" / "auto-candidates.jsonl"


def read_pending(mem):
    path = pending_path(mem)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def commit_lesson(repo, name="learn.txt", message="lesson: deploys need a clean tree"):
    (repo / name).write_text("body\n")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)


def test_install_writes_a_quiet_post_commit_hook(repo, mem, capsys):
    code, out = install(capsys, "--agent", "generic")
    assert code == 0
    path = hook(repo, "post-commit")
    assert path.is_file() and path.stat().st_mode & 0o111
    text = path.read_text()
    assert "hook post-commit" in text and "|| true" in text
    assert "timeout -k 1 1 " in text or "gtimeout -k 1 1 " in text or "alarm 1;" in text
    assert text.count(githook.START) == 1
    assert "post-commit" in out or path.exists()


def test_no_git_hook_skips_post_commit(repo, mem, capsys):
    code, _ = install(capsys, "--agent", "generic", "--no-git-hook")
    assert code == 0
    assert not hook(repo, "post-commit").exists()


def test_post_commit_drafts_pending_candidates_from_the_commit(repo, mem, capsys):
    install(capsys, "--agent", "generic")
    commit_lesson(repo)
    found = [rec for rec in read_pending(mem) if rec.get("type", "candidate") == "candidate"]
    assert found, "post-commit must draft at least one pending candidate"
    cand = found[0]
    assert cand["status"] == "pending"
    assert cand["kind"] in ("lesson", "decision", "trap", "fact")
    assert "clean tree" in cand["text"].lower() or "lesson" in cand["text"].lower()
    assert cand["source"].startswith("commit:")
    assert cand["id"].startswith("c-")


def test_pending_candidates_are_not_loaded_as_facts(repo, mem, capsys):
    install(capsys, "--agent", "generic")
    commit_lesson(repo)
    assert read_pending(mem)
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "pending" not in out.lower() or "auto-candidates" not in out
    # No fact id from the pending store appears in load.
    for rec in read_pending(mem):
        if rec.get("type", "candidate") == "candidate":
            assert rec["id"] not in out


def test_post_commit_hook_never_fails_git(repo, mem, capsys):
    install(capsys, "--agent", "generic")
    (repo / "ok.txt").write_text("x\n")
    git(repo, "add", "ok.txt")
    result = subprocess.run(
        ["git", "commit", "-q", "-m", "lesson: always exit 0"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Traceback" not in result.stdout + result.stderr


def test_candidates_list_shows_pending(repo, mem, capsys):
    install(capsys, "--agent", "generic")
    commit_lesson(repo)
    capsys.readouterr()
    assert main(["candidates", "list"]) == 0
    out = capsys.readouterr().out
    assert "pending" in out.lower()
    assert "c-" in out


def test_post_commit_is_fast(mem, monkeypatch, capsys):
    """The in-process post-commit budget is ~1s, not the 3s fuller budget."""
    started = {"yes": False}
    finished = {"yes": False}

    def slow(*args, **kwargs):
        started["yes"] = True
        time.sleep(30)
        finished["yes"] = True

    monkeypatch.setattr("cairnkit.propose.draft_from_head", slow)
    capsys.readouterr()
    began = time.monotonic()
    assert main(["hook", "post-commit"]) == 0
    assert time.monotonic() - began < 4
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
    assert started["yes"] and not finished["yes"]
