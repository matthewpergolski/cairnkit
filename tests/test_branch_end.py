"""When the work of a branch is done. A false end is worse than a stale note."""

from __future__ import annotations

import shutil

import pytest
from conftest import add_worktree, git

from cairnkit import autotidy
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import branch_exists, find_project, merged_checker

ADD = ["--area", "x", "--basis", "seen", "--source", "session:1"]


def _commit(repo, name):
    (repo / name).write_text(f"{name}\n")
    git(repo, "add", name)
    git(repo, "commit", "-qm", f"add {name}")


def _work(repo, *files):
    git(repo, "switch", "-qc", "work")
    for name in files:
        _commit(repo, name)


def _load(capsys):
    capsys.readouterr()
    assert main(["load", "--budget", "0"]) == 0
    return capsys.readouterr().out


def test_a_note_on_a_branch_behind_its_base_still_loads(mem, repo, capsys):
    git(repo, "switch", "-qc", "feat/live")
    assert main(["add", "Live note.", "--short", *ADD]) == 0
    git(repo, "switch", "-q", "main")
    _commit(repo, "on-main")
    git(repo, "switch", "-q", "feat/live")
    assert "Live note." in _load(capsys)


def test_auto_tidy_does_not_end_a_note_on_a_branch_behind_its_base(mem, repo, capsys):
    git(repo, "switch", "-qc", "feat/live")
    assert main(["add", "Live note.", "--short", *ADD]) == 0
    git(repo, "switch", "-q", "main")
    _commit(repo, "on-main")
    assert autotidy.find(Memory.open(find_project(), None)) == []
    git(repo, "switch", "-q", "feat/live")
    assert "Live note." in _load(capsys)


def test_a_fresh_branch_behind_its_base_is_live(repo):
    git(repo, "branch", "work")
    _commit(repo, "on-main")
    assert merged_checker(repo)("work") is False


def test_a_fresh_branch_brought_up_to_its_base_is_live(repo):
    git(repo, "switch", "-qc", "work")
    git(repo, "switch", "-q", "main")
    _commit(repo, "one")
    git(repo, "switch", "-q", "work")
    git(repo, "merge", "-q", "main")
    git(repo, "switch", "-q", "main")
    _commit(repo, "two")
    assert merged_checker(repo)("work") is False


def test_a_branch_with_only_an_empty_commit_is_live(repo):
    _work(repo)
    git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
    git(repo, "switch", "-q", "main")
    assert merged_checker(repo)("work") is False


def test_a_commit_and_its_revert_is_live(repo):
    _work(repo, "a")
    git(repo, "revert", "--no-edit", "HEAD")
    git(repo, "switch", "-q", "main")
    assert merged_checker(repo)("work") is False


def test_a_commit_cherry_picked_to_the_base_is_live(repo):
    _work(repo, "a")
    git(repo, "switch", "-q", "main")
    _commit(repo, "on-main")
    git(repo, "cherry-pick", "work")
    assert merged_checker(repo)("work") is False


def test_a_commit_that_was_thrown_away_is_live(repo):
    _work(repo, "a")
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    git(repo, "switch", "-q", "main")
    _commit(repo, "on-main")
    assert merged_checker(repo)("work") is False


def test_a_merged_branch_that_is_checked_out_is_live_until_the_developer_leaves(repo):
    path = add_worktree(repo, "work")
    _commit(path, "a")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "work")
    assert merged_checker(repo)("work") is False
    git(repo, "worktree", "remove", str(path))
    assert merged_checker(repo)("work") is True


def test_a_worktree_folder_that_is_gone_does_not_hold_a_branch_open(repo):
    path = add_worktree(repo, "work")
    _commit(path, "a")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "work")
    shutil.rmtree(path)
    assert merged_checker(repo)("work") is True


@pytest.mark.parametrize("how", ["--ff", "--no-ff"])
def test_a_true_merge_ends_the_note_after_the_developer_leaves(mem, repo, capsys, how):
    _work(repo, "a")
    assert main(["add", "Note on work.", "--short", *ADD]) == 0
    assert merged_checker(repo)("work") is False
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", how, "--no-edit", "work")
    assert merged_checker(repo)("work") is True
    assert [item.case for item in autotidy.find(Memory.open(find_project(), None))] == ["ended"]


def test_a_merge_after_a_rebase_ends_the_note(repo):
    _work(repo, "a")
    git(repo, "switch", "-q", "main")
    _commit(repo, "on-main")
    git(repo, "switch", "-q", "work")
    git(repo, "rebase", "-q", "main")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "work")
    assert merged_checker(repo)("work") is True


def test_a_one_commit_squash_reads_as_merged(repo):
    _work(repo, "a")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--squash", "work")
    git(repo, "commit", "-qm", "work (#12)")
    assert merged_checker(repo)("work") is True


def test_with_no_reflog_a_merged_branch_stays_live(repo):
    git(repo, "config", "core.logAllRefUpdates", "false")
    _work(repo, "a")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "work")
    assert merged_checker(repo)("work") is False


def test_a_renamed_branch_is_followed(repo):
    _work(repo, "a")
    git(repo, "branch", "-m", "work", "better")
    assert merged_checker(repo)("work") is False
    git(repo, "switch", "-q", "main")
    git(repo, "branch", "-m", "better", "best")
    assert merged_checker(repo)("work") is False


def test_a_git_failure_does_not_end_a_note(repo, monkeypatch):
    checker = merged_checker(repo)
    monkeypatch.setattr("cairnkit.paths.run_git", lambda *args, **kwargs: None)
    assert checker("gone") is False


def test_a_renamed_branch_ends_when_its_new_name_merges(repo):
    _work(repo, "a")
    git(repo, "branch", "-m", "work", "better")
    git(repo, "switch", "-q", "main")
    assert merged_checker(repo)("work") is False
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "better")
    assert merged_checker(repo)("work") is True


def test_a_renamed_branch_ends_when_its_new_name_is_deleted(repo):
    _work(repo, "a")
    git(repo, "branch", "-m", "work", "better")
    git(repo, "switch", "-q", "main")
    git(repo, "branch", "-qD", "better")
    assert merged_checker(repo)("work") is True


def test_a_branch_renamed_to_the_base_is_live(repo):
    git(repo, "branch", "-m", "main", "old")
    git(repo, "branch", "-m", "old", "main")
    assert merged_checker(repo)("old") is False


def test_branch_exists_reads_only_branches(repo):
    git(repo, "tag", "v1")
    git(repo, "branch", "work")
    git(repo, "update-ref", "refs/remotes/origin/far", "HEAD")
    assert branch_exists(repo, "work")
    assert branch_exists(repo, "far")
    assert branch_exists(repo, "origin/far")
    assert not branch_exists(repo, "v1")
    assert not branch_exists(repo, "HEAD")
    assert not branch_exists(repo, "gone")
