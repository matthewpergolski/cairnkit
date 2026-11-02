"""A `held_by` file that another checkout holds is no problem for this checkout."""

from __future__ import annotations

from conftest import add_worktree, git

from cairnkit.cli import main


def _held(capsys, path, name="only.md") -> str:
    capsys.readouterr()
    assert main(["add", "A rule that a file holds now."]) == 0
    fact = capsys.readouterr().out.split("added ")[1].split()[0]
    assert main(["change", fact, "--status", "promoted", "--held-by", name, "--reason", "r"]) == 0
    return fact


def test_a_file_not_yet_committed_in_another_worktree_gives_no_error(
    mem, repo, capsys, monkeypatch
):
    other = add_worktree(repo, "work")
    (other / "only.md").write_text("x\n")
    monkeypatch.chdir(other)
    _held(capsys, other)
    monkeypatch.chdir(repo)
    assert main(["check", "--strict"]) == 0
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-qm", "unrelated")


def test_a_file_gone_from_every_checkout_and_all_history_is_still_named(
    mem, repo, capsys, monkeypatch
):
    other = add_worktree(repo, "work")
    (other / "only.md").write_text("x\n")
    monkeypatch.chdir(other)
    fact = _held(capsys, other)
    (other / "only.md").unlink()
    monkeypatch.chdir(repo)
    capsys.readouterr()
    assert main(["check"]) == 1
    assert f"{fact}: held_by only.md does not exist" in capsys.readouterr().out
