"""A branch from before the migration tracks memory-bank/. Git replaces the link with it."""

from conftest import git

from cairnkit.cli import main


def old_branch(repo):
    git(repo, "switch", "-qc", "preexisting")
    (repo / "memory-bank").mkdir()
    (repo / "memory-bank" / "status.md").write_text("old status: PR 96 is open\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "old layout")
    git(repo, "switch", "-q", "main")


def load(capsys):
    capsys.readouterr()
    assert main(["load"]) == 0
    return capsys.readouterr().out


def test_load_says_the_folder_is_not_the_memory(repo, capsys):
    old_branch(repo)
    assert main(["init", "--no-default-rules"]) == 0
    assert main(["add", "real fact"]) == 0
    git(repo, "switch", "-q", "preexisting")
    assert (repo / "memory-bank").is_dir() and not (repo / "memory-bank").is_symlink()
    out = load(capsys)
    assert "real fact" in out
    head = out.splitlines()[:3]
    warning = next(line for line in head if line.startswith("warning:"))
    assert "real folder" in warning and "this branch" in warning
    assert str(repo.parent / "proj.memory") in warning
    assert "old" in warning


def test_session_start_carries_the_warning(repo, capsys):
    old_branch(repo)
    assert main(["init", "--no-default-rules"]) == 0
    git(repo, "switch", "-q", "preexisting")
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "pi"]) == 0
    assert "real folder" in capsys.readouterr().out


def test_back_on_main_the_link_returns_and_the_warning_goes(repo, capsys):
    old_branch(repo)
    assert main(["init", "--no-default-rules"]) == 0
    git(repo, "switch", "-q", "preexisting")
    load(capsys)
    git(repo, "switch", "-q", "main")
    out = load(capsys)
    assert (repo / "memory-bank").is_symlink()
    assert "real folder" not in out


def test_a_renamed_repo_on_the_old_branch_still_finds_the_memory(repo, capsys, monkeypatch):
    old_branch(repo)
    assert main(["init", "--no-default-rules"]) == 0
    assert main(["add", "real fact"]) == 0
    load(capsys)
    git(repo, "switch", "-q", "preexisting")
    new = repo.parent / "renamed"
    repo.rename(new)
    monkeypatch.chdir(new)
    out = load(capsys)
    assert "real fact" in out and "real folder" in out


def test_an_untracked_real_folder_is_named_too(repo, mem, capsys):
    (repo / "memory-bank").unlink()
    (repo / "memory-bank").mkdir()
    (repo / "memory-bank" / "x.md").write_text("x\n")
    out = load(capsys)
    assert "real folder" in out
    assert "this branch" not in out


def test_a_normal_load_has_no_warning(repo, mem, capsys):
    assert "warning:" not in load(capsys)
