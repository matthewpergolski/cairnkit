"""A plain folder (no git): subfolders find the project, init does not make a second memory."""

from pathlib import Path

from conftest import read_jsonl

from cairnkit.cli import main
from cairnkit.paths import find_project

BASE = ["--area", "x", "--basis", "seen", "--source", "session:2026-10-23"]


def plain_project(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    plain = home / "plain"
    (plain / "sub" / "deep").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(plain)
    assert main(["init", "--no-default-rules"]) == 0
    return plain


def test_subfolder_finds_the_project_root(tmp_path, monkeypatch, capsys):
    plain = plain_project(tmp_path, monkeypatch)
    monkeypatch.chdir(plain / "sub" / "deep")
    assert find_project().root == plain
    capsys.readouterr()
    assert main(["add", "From a subfolder.", *BASE]) == 0
    [rec] = read_jsonl(tmp_path / "home" / "plain.memory" / "facts" / "main.jsonl")
    assert rec["text"] == "From a subfolder."
    assert not (plain / "sub" / "deep.memory").exists()


def test_memory_path_file_marks_the_root(tmp_path, monkeypatch):
    home = tmp_path / "home"
    plain = home / "plain"
    (plain / "sub").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    (plain / ".memory-path").write_text("../elsewhere.memory\n")
    monkeypatch.chdir(plain / "sub")
    assert find_project().root == plain


def test_init_in_a_subfolder_refuses(tmp_path, monkeypatch, capsys):
    plain = plain_project(tmp_path, monkeypatch)
    monkeypatch.chdir(plain / "sub")
    capsys.readouterr()
    assert main(["init"]) == 1
    err = capsys.readouterr().err
    assert str(plain) in err and "already" in err
    assert not (plain / "sub" / "memory-bank").exists()
    assert not (tmp_path / "home" / "plain" / "sub.memory").exists()


def test_env_and_flag_still_win(tmp_path, monkeypatch, capsys):
    plain = plain_project(tmp_path, monkeypatch)
    other = tmp_path / "other.memory"
    monkeypatch.chdir(plain / "sub")
    assert main(["init", "--path", str(other), "--no-default-rules"]) == 1  # still refused
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "home" / "plain.memory"))
    capsys.readouterr()
    assert main(["add", "Via MEMORY_DIR.", *BASE]) == 0


def test_walk_stops_at_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "a" / "b").mkdir(parents=True)
    (home / "memory-bank").symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home / "a" / "b")
    assert find_project().root == home / "a" / "b"


def test_no_marker_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "x" / "y").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "x" / "y")
    assert find_project().root == tmp_path / "x" / "y"


def test_git_subfolder_is_unchanged(repo, monkeypatch):
    (repo / "src").mkdir()
    (repo / "src" / "memory-bank").symlink_to(repo, target_is_directory=True)
    monkeypatch.chdir(repo / "src")
    assert find_project().root == repo


def test_until_merged_outside_git_says_it_needs_git(tmp_path, monkeypatch, capsys):
    plain_project(tmp_path, monkeypatch)
    capsys.readouterr()
    assert main(["add", "Note.", *BASE, "--until-merged"]) == 1
    err = capsys.readouterr().err
    assert "git repo" in err and "detached" not in err


def test_until_merged_on_detached_head_keeps_its_message(repo, mem, capsys):
    from conftest import git

    git(repo, "checkout", "-q", "--detach")
    capsys.readouterr()
    assert main(["add", "Note.", *BASE, "--until-merged"]) == 1
    assert "detached" in capsys.readouterr().err
