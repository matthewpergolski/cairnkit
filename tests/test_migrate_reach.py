"""`memory migrate` from one checkout changes the index and the tool files of that checkout only."""

import pytest
from conftest import add_worktree, git

from cairnkit import hooks_cmd
from cairnkit.cli import main


@pytest.fixture
def tracked_notes(repo):
    """Old notes tracked in git, with a worktree that has them too, and Claude Code in use."""
    (repo / "memory-bank").mkdir()
    (repo / "memory-bank" / "status.md").write_text("# Status\n")
    git(repo, "add", "memory-bank")
    git(repo, "commit", "-q", "-m", "notes")
    (repo / ".claude").mkdir()
    return repo


def staged(checkout):
    return git(checkout, "diff", "--cached", "--name-only").split()


def test_a_run_from_a_worktree_stages_only_there(tracked_notes, capsys, monkeypatch):
    worktree = add_worktree(tracked_notes, "topic")
    monkeypatch.chdir(worktree)
    capsys.readouterr()
    assert main(["migrate", "--yes", "--untrack"]) == 0
    out = capsys.readouterr().out
    assert staged(worktree) == ["memory-bank/status.md"]
    assert staged(tracked_notes) == []
    assert f"git -C {tracked_notes} rm -r --cached memory-bank" in out


def test_a_run_from_main_stages_only_there(tracked_notes, capsys, monkeypatch):
    worktree = add_worktree(tracked_notes, "topic")
    capsys.readouterr()
    assert main(["migrate", "--yes", "--untrack"]) == 0
    out = capsys.readouterr().out
    assert staged(tracked_notes) == ["memory-bank/status.md"]
    assert staged(worktree) == []
    assert f"git -C {worktree} rm -r --cached memory-bank" in out


def test_the_plan_names_the_same_reach(tracked_notes, capsys, monkeypatch):
    worktree = add_worktree(tracked_notes, "topic")
    monkeypatch.chdir(worktree)
    capsys.readouterr()
    assert main(["migrate", "--untrack"]) == 0
    out = capsys.readouterr().out
    assert f"would run git rm -r --cached memory-bank in {worktree}" in out
    assert f"git rm -r --cached memory-bank in {tracked_notes}\n" not in out
    assert staged(worktree) == [] and staged(tracked_notes) == []


def test_agent_files_go_to_this_checkout_and_the_others_are_named(
    tracked_notes, capsys, monkeypatch
):
    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    worktree = add_worktree(tracked_notes, "topic")
    (worktree / ".claude").mkdir(exist_ok=True)
    monkeypatch.chdir(worktree)
    capsys.readouterr()
    assert main(["migrate", "--yes", "--untrack"]) == 0
    out = capsys.readouterr().out
    assert (worktree / ".claude" / "settings.local.json").is_file()
    assert not (tracked_notes / ".claude" / "settings.local.json").exists()
    assert f"not connected: {tracked_notes}" in out
    assert (tracked_notes / "memory-bank").is_symlink()


def test_a_later_load_in_the_other_checkout_still_works(tracked_notes, capsys, monkeypatch):
    worktree = add_worktree(tracked_notes, "topic")
    monkeypatch.chdir(worktree)
    assert main(["migrate", "--yes", "--untrack"]) == 0
    monkeypatch.chdir(tracked_notes)
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "not loaded" not in capsys.readouterr().out
