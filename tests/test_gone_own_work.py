"""A stop asks about a lost file only when this session deleted it, not when a commit came in."""

from __future__ import annotations

import io
import json
import shutil

import pytest
from conftest import git

from cairnkit.cli import main

LOST = "when this session started"
THEIRS = "src/theirs.py"
OWN = "src/own.py"


def plant(repo):
    (repo / "src").mkdir()
    for path in (THEIRS, OWN):
        (repo / path).write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", "src")
    git(repo, "commit", "-qm", "two files")


@pytest.fixture
def other(repo, mem, tmp_path):
    """Another person's clone, with a commit that removes a file. It sits in FETCH_HEAD to pull."""
    plant(repo)
    clone = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(repo), str(clone))
    git(clone, "config", "user.name", "Other")
    git(clone, "config", "user.email", "other@example.com")
    git(clone, "rm", "-q", THEIRS)
    git(clone, "commit", "-qm", "remove their file")
    return clone


def run_hook(capsys, monkeypatch, event):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s"})))
    capsys.readouterr()
    main(["hook", event, "--agent", "claude"])
    return capsys.readouterr().out


def start(capsys, monkeypatch):
    run_hook(capsys, monkeypatch, "session-start")


def stop(capsys, monkeypatch):
    return run_hook(capsys, monkeypatch, "stop")


def own_rm_and_commit(repo):
    git(repo, "rm", "-q", OWN)
    git(repo, "commit", "-qm", "remove my file")


def pull(repo, other):
    git(repo, "pull", "-q", "--ff-only", str(other), "main")


def fetch(repo, other):
    git(repo, "fetch", "-q", str(other), "main")


def merge_no_ff(repo, other):
    fetch(repo, other)
    git(repo, "merge", "-q", "--no-ff", "-m", "merge theirs", "FETCH_HEAD")


def fast_forward(repo, other):
    fetch(repo, other)
    git(repo, "merge", "-q", "--ff-only", "FETCH_HEAD")


def switch(repo, other):
    fetch(repo, other)
    git(repo, "switch", "-q", "-c", "theirs", "FETCH_HEAD")


def reset_to(repo, other):
    fetch(repo, other)
    git(repo, "reset", "-q", "--hard", "FETCH_HEAD")


def rebase_onto(repo, other):
    fetch(repo, other)
    (repo / "added.txt").write_text("mine\n", encoding="utf-8")
    git(repo, "add", "added.txt")
    git(repo, "commit", "-qm", "my work")
    git(repo, "rebase", "-q", "FETCH_HEAD")


def pull_rebase(repo, other):
    (repo / "added.txt").write_text("mine\n", encoding="utf-8")
    git(repo, "add", "added.txt")
    git(repo, "commit", "-qm", "my work")
    git(repo, "pull", "-q", "--rebase", str(other), "main")


@pytest.mark.parametrize(
    "bring_in",
    [pull, fast_forward, merge_no_ff, switch, reset_to, rebase_onto, pull_rebase],
)
def test_commits_from_elsewhere_raise_no_question(repo, other, capsys, monkeypatch, bring_in):
    start(capsys, monkeypatch)
    bring_in(repo, other)
    assert not (repo / THEIRS).exists()
    assert LOST not in stop(capsys, monkeypatch)


def test_a_local_git_rm_and_commit_raises_the_question(repo, other, capsys, monkeypatch):
    start(capsys, monkeypatch)
    own_rm_and_commit(repo)
    said = stop(capsys, monkeypatch)
    assert LOST in said and OWN in said


def test_a_file_deleted_in_the_worktree_raises_the_question(repo, other, capsys, monkeypatch):
    start(capsys, monkeypatch)
    (repo / OWN).unlink()
    said = stop(capsys, monkeypatch)
    assert LOST in said and OWN in said


@pytest.mark.parametrize("own_first", [True, False])
def test_a_pull_and_an_own_commit_name_only_the_own_file(
    repo, other, capsys, monkeypatch, own_first
):
    start(capsys, monkeypatch)
    if own_first:
        own_rm_and_commit(repo)
        fetch(repo, other)
        git(repo, "merge", "-q", "-m", "merge theirs", "FETCH_HEAD")
    else:
        pull(repo, other)
        own_rm_and_commit(repo)
    said = stop(capsys, monkeypatch)
    assert LOST in said and OWN in said
    assert THEIRS not in said


def test_an_own_commit_that_a_later_commit_undoes_raises_no_question(
    repo, other, capsys, monkeypatch
):
    start(capsys, monkeypatch)
    own_rm_and_commit(repo)
    git(repo, "revert", "--no-edit", "HEAD")
    assert (repo / OWN).exists()
    assert LOST not in stop(capsys, monkeypatch)


def test_a_commit_from_before_the_session_does_not_count_as_own(repo, other, capsys, monkeypatch):
    """The reflog holds an old `git rm` of this path, from before the file came back."""
    own_rm_and_commit(repo)
    git(repo, "revert", "--no-edit", "HEAD")
    git(other, "rm", "-q", OWN)
    git(other, "commit", "-qm", "remove the same file")
    start(capsys, monkeypatch)
    fetch(repo, other)
    git(repo, "merge", "-q", "-m", "merge theirs", "FETCH_HEAD")
    assert not (repo / OWN).exists()
    assert LOST not in stop(capsys, monkeypatch)


def reflog_off(repo):
    git(repo, "config", "core.logAllRefUpdates", "false")
    shutil.rmtree(repo / ".git" / "logs")


def test_with_the_reflog_off_a_pull_raises_no_question(repo, other, capsys, monkeypatch):
    reflog_off(repo)
    start(capsys, monkeypatch)
    pull(repo, other)
    assert not (repo / THEIRS).exists()
    assert LOST not in stop(capsys, monkeypatch)


def test_with_the_reflog_off_a_worktree_deletion_still_raises_it(repo, other, capsys, monkeypatch):
    reflog_off(repo)
    start(capsys, monkeypatch)
    (repo / OWN).unlink()
    said = stop(capsys, monkeypatch)
    assert LOST in said and OWN in said


def test_with_the_reflog_off_an_own_commit_cannot_be_told_from_a_pull(
    repo, other, capsys, monkeypatch
):
    reflog_off(repo)
    start(capsys, monkeypatch)
    own_rm_and_commit(repo)
    assert LOST not in stop(capsys, monkeypatch)
