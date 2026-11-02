"""A note ends when git shows that its work landed. Absence alone never says that it did."""

from __future__ import annotations

import pytest
from conftest import git

from cairnkit.cli import main


def _commit(path, name, text="one\n"):
    (path / name).write_text(text)
    git(path, "add", name)
    git(path, "commit", "-qm", f"change {name} to {text.strip()}")


def _note(capsys, *args) -> str:
    capsys.readouterr()
    assert main(["add", "A note on this work.", *args]) == 0
    return capsys.readouterr().out.split("added ")[1].split()[0]


def _tidy(capsys) -> str:
    capsys.readouterr()
    assert main(["tidy", "--auto", "--dry-run"]) == 0
    return capsys.readouterr().out


def _squash(repo, branch, into="main"):
    git(repo, "switch", "-q", into)
    git(repo, "merge", "-q", "--squash", branch)
    git(repo, "commit", "-qm", f"{branch} (#1)")


def _work(repo, capsys, branch="work") -> str:
    git(repo, "switch", "-qc", branch)
    _commit(repo, f"{branch}.txt")
    return _note(capsys, "--short")


@pytest.fixture
def remote(repo, tmp_path):
    bare = tmp_path / "bare.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    git(repo, "remote", "set-head", "origin", "main")
    return bare


def test_a_squash_ends_the_note_after_the_base_changes_the_same_lines(mem, repo, capsys):
    fact = _work(repo, capsys)
    _squash(repo, "work")
    _commit(repo, "work.txt", "two\n")
    assert fact in _tidy(capsys)


def test_a_squash_of_many_commits_ends_the_note_after_the_base_moves(mem, repo, capsys):
    fact = _work(repo, capsys)
    _commit(repo, "second.txt")
    _squash(repo, "work")
    _commit(repo, "work.txt", "two\n")
    assert fact in _tidy(capsys)


def test_a_branch_with_another_change_to_the_same_file_stays(mem, repo, capsys):
    fact = _work(repo, capsys)
    git(repo, "switch", "-q", "main")
    _commit(repo, "work.txt", "other\n")
    assert fact not in _tidy(capsys)


def test_a_squash_with_the_remote_copy_kept_ends_the_note(mem, repo, capsys, remote):
    fact = _work(repo, capsys)
    git(repo, "push", "-q", "-u", "origin", "work")
    _squash(repo, "work")
    git(repo, "branch", "-qD", "work")
    assert fact in _tidy(capsys)


def test_a_merge_commit_with_the_remote_copy_kept_ends_the_note(mem, repo, capsys, remote):
    fact = _work(repo, capsys)
    git(repo, "push", "-q", "-u", "origin", "work")
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "work")
    git(repo, "branch", "-qD", "work")
    assert fact in _tidy(capsys)


def test_a_remote_copy_with_work_that_did_not_land_stays(mem, repo, capsys, remote):
    fact = _work(repo, capsys)
    git(repo, "push", "-q", "-u", "origin", "work")
    git(repo, "switch", "-q", "main")
    git(repo, "branch", "-qD", "work")
    assert fact not in _tidy(capsys)


def test_a_remote_copy_with_no_commit_of_its_own_stays(mem, repo, capsys, remote):
    git(repo, "switch", "-qc", "work")
    fact = _note(capsys, "--short")
    git(repo, "push", "-q", "-u", "origin", "work")
    git(repo, "switch", "-q", "main")
    git(repo, "branch", "-qD", "work")
    assert fact not in _tidy(capsys)


def test_a_remote_copy_that_gets_new_work_after_a_squash_stays(mem, repo, capsys, remote):
    fact = _work(repo, capsys)
    _commit(repo, "more.txt")
    git(repo, "push", "-q", "-u", "origin", "work")
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    _squash(repo, "work")
    git(repo, "branch", "-qD", "work")
    assert fact not in _tidy(capsys)


def test_a_squash_seen_only_on_the_remote_base_ends_the_note(mem, repo, capsys, remote):
    fact = _work(repo, capsys)
    git(repo, "switch", "-qc", "elsewhere", "main")
    git(repo, "merge", "-q", "--squash", "work")
    git(repo, "commit", "-qm", "work (#1)")
    git(repo, "push", "-q", "origin", "elsewhere:main")
    git(repo, "fetch", "-q")
    assert git(repo, "rev-parse", "main") != git(repo, "rev-parse", "origin/main")
    assert fact in _tidy(capsys)


@pytest.mark.parametrize("integration", ["dev", "develop"])
def test_a_squash_into_an_integration_branch_ends_the_note(mem, repo, capsys, remote, integration):
    git(repo, "branch", integration)
    fact = _work(repo, capsys)
    _squash(repo, "work", into=integration)
    assert fact in _tidy(capsys)


def test_a_merge_into_any_other_branch_ends_nothing(mem, repo, capsys):
    git(repo, "branch", "stack")
    fact = _work(repo, capsys)
    _squash(repo, "work", into="stack")
    assert fact not in _tidy(capsys)


def test_a_note_on_the_integration_branch_ends_when_it_reaches_the_default(mem, repo, capsys):
    git(repo, "switch", "-qc", "dev")
    _commit(repo, "dev.txt")
    fact = _note(capsys, "--short")
    assert fact not in _tidy(capsys)
    git(repo, "switch", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "dev")
    git(repo, "switch", "-qc", "next")
    git(repo, "branch", "-qD", "dev")
    assert fact in _tidy(capsys)


def test_a_deleted_branch_with_work_that_did_not_land_stays_and_tidy_names_it(mem, repo, capsys):
    fact = _work(repo, capsys)
    git(repo, "switch", "-q", "main")
    git(repo, "branch", "-qD", "work")
    out = _tidy(capsys)
    assert "Nothing to retire." in out
    assert "unknown" in out and fact in out


def test_a_deleted_branch_whose_recorded_work_was_squashed_ends_the_note(mem, repo, capsys):
    fact = _work(repo, capsys)
    _squash(repo, "work")
    _commit(repo, "work.txt", "two\n")
    git(repo, "branch", "-qD", "work")
    assert "Would retire" in _tidy(capsys)
    assert fact in _tidy(capsys)


def test_a_rule_until_merged_stops_loading_after_a_squash_and_a_later_change(mem, repo, capsys):
    git(repo, "switch", "-qc", "work")
    _commit(repo, "work.txt")
    assert main(["add", "Rebase this work first.", "--kind", "rule", "--until-merged"]) == 0
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "Rebase this work first." in capsys.readouterr().out
    _squash(repo, "work")
    _commit(repo, "work.txt", "two\n")
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "Rebase this work first." not in capsys.readouterr().out
