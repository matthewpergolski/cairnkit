"""A folder beside a project is named only under a name that the project is known to have had."""

from __future__ import annotations

import shutil

import pytest
from conftest import git

from cairnkit.cli import main

FACT = "Trap: billing webhook retries forever"
NOTE = "could be its own under an earlier name"


def run(capsys, *args):
    capsys.readouterr()
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def orphan(parent, name):
    """A memory from before the id and the record: only its files say what it is."""
    folder = parent / f"{name}.memory"
    (folder / "facts").mkdir(parents=True)
    (folder / "config.toml").write_text("")
    return folder


def new_repo(parent, name):
    folder = parent / name
    folder.mkdir(parents=True)
    git(folder, "init", "-q", "-b", "main")
    git(folder, "config", "user.name", "Test")
    git(folder, "config", "user.email", "t@example.invalid")
    (folder / "a.txt").write_text(name)
    git(folder, "add", "a.txt")
    git(folder, "commit", "-q", "-m", f"first of {name}")
    return folder


def test_a_fresh_clone_is_not_offered_an_unrelated_orphan(tmp_path, monkeypatch, capsys):
    source = new_repo(tmp_path, "h1")
    orphan(tmp_path, "g4")
    clone = tmp_path / "h1clone"
    git(tmp_path, "clone", "-q", str(source), str(clone))
    monkeypatch.chdir(clone)
    for command in ("load", "check"):
        assert "g4.memory" not in run(capsys, command)[1]
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert "g4.memory" not in out
    assert "g4.memory" not in run(capsys, "load")[1]


def test_a_project_is_offered_a_folder_named_for_its_remote(tmp_path, monkeypatch, capsys):
    source = new_repo(tmp_path, "src")
    git(source, "remote", "add", "origin", "git@github.com:someone/g4.git")
    folder = orphan(tmp_path, "g4")
    monkeypatch.chdir(source)
    _, out = run(capsys, "load")
    assert f"memory init --path {folder}" in out


@pytest.mark.parametrize(
    "url",
    ["https://example.com/a/g4.git", "https://example.com/a/g4/", "git@example.com:g4", "../g4"],
)
def test_each_shape_of_url_names_the_project(tmp_path, monkeypatch, capsys, url):
    source = new_repo(tmp_path, "src")
    git(source, "remote", "add", "origin", url)
    folder = orphan(tmp_path, "g4")
    monkeypatch.chdir(source)
    assert f"memory init --path {folder}" in run(capsys, "load")[1]


def test_a_recorded_earlier_name_counts(repo, mem, capsys, tmp_path, monkeypatch):
    assert main(["load"]) == 0
    record = repo / ".git" / "cairnkit-memory"
    lines = record.read_text().splitlines()
    record.write_text(f"{lines[0]}\n{mem}\n{tmp_path / 'g4' / '.git'}\n")
    shutil.rmtree(mem)
    (repo / "memory-bank").unlink()
    folder = orphan(tmp_path, "g4")
    monkeypatch.chdir(repo)
    assert f"memory init --path {folder}" in run(capsys, "load")[1]


@pytest.fixture
def made_beside(tmp_path, monkeypatch, capsys):
    """A connected project that session start gave a new memory, beside a likely earlier one."""
    source = new_repo(tmp_path, "g4new")
    git(source, "remote", "add", "origin", "https://example.com/a/g4.git")
    earlier = orphan(tmp_path, "g4")
    monkeypatch.chdir(source)
    (source / ".claude").mkdir()
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    code, out = run(capsys, "hook", "session-start", "--agent", "claude")
    assert code == 0 and "not loaded" not in out
    assert (tmp_path / "g4new.memory" / "facts").is_dir()
    assert f"memory init --path {earlier}" in out
    return source, earlier


def test_the_note_stays_after_many_sessions_and_notes(made_beside, capsys):
    _, earlier = made_beside
    assert main(["add", "first fact in the hook made memory"]) == 0
    for session in range(3):
        _, out = run(capsys, "hook", "session-start", "--agent", "claude")
        assert f"memory init --path {earlier}" in out, session
        assert f"memory init --path {earlier}" in run(capsys, "load")[1]
        code, out = run(capsys, "check")
        assert code == 0 and f"memory init --path {earlier}" in out


def test_adopting_the_folder_ends_the_note(made_beside, capsys):
    source, earlier = made_beside
    (earlier / "facts" / "main.jsonl").write_text("")
    assert run(capsys, "init", "--no-default-rules", "--path", str(earlier))[0] == 0
    assert (source / "memory-bank").resolve() == earlier.resolve()
    assert NOTE not in run(capsys, "load")[1]
    assert NOTE not in run(capsys, "check")[1]


def test_the_owner_can_state_otherwise_with_a_local_setting(made_beside, capsys):
    source, earlier = made_beside
    printed = next(ln for ln in run(capsys, "load")[1].splitlines() if NOTE in ln)
    assert f"git config --add cairnkit.notearlier {earlier.name}" in printed
    git(source, "config", "--add", "cairnkit.notearlier", earlier.name)
    assert NOTE not in run(capsys, "load")[1]
    assert NOTE not in run(capsys, "check")[1]


def test_the_setting_names_one_folder_so_another_is_still_said(made_beside, capsys, tmp_path):
    source, earlier = made_beside
    git(source, "config", "--add", "cairnkit.notearlier", earlier.name)
    git(source, "config", "user.name", "Test")
    other = orphan(tmp_path, "g5")
    git(source, "remote", "set-url", "origin", "https://example.com/a/g5.git")
    assert f"memory init --path {other}" in run(capsys, "load")[1]


def test_the_note_ends_when_no_such_folder_sits_there(made_beside, capsys):
    _, earlier = made_beside
    shutil.rmtree(earlier)
    assert NOTE not in run(capsys, "load")[1]
    assert NOTE not in run(capsys, "check")[1]


def test_a_folder_of_another_history_is_not_named_even_with_the_name(tmp_path, monkeypatch, capsys):
    source = new_repo(tmp_path, "src")
    git(source, "remote", "add", "origin", "https://example.com/a/g4.git")
    folder = orphan(tmp_path, "g4")
    (folder / ".identity").write_text("some-id\n" + "0" * 40 + "\n")
    monkeypatch.chdir(source)
    assert "g4.memory" not in run(capsys, "load")[1]


def test_the_memory_in_use_is_never_named(made_beside, capsys, tmp_path):
    source, _ = made_beside
    own = tmp_path / "g4new.memory"
    assert str(own) not in next(ln for ln in run(capsys, "load")[1].splitlines() if NOTE in ln)
    assert (source / "memory-bank").resolve() == own.resolve()
