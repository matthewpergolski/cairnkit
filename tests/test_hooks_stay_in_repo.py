"""Hooks stay in the repo's git folder: a rename cannot break them, and no repo shares them.

The attribution line here is a fixture that the guard must refuse.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
from conftest import add_worktree, git

from cairnkit import githook
from cairnkit.cli import main
from cairnkit.paths import find_project

RULE = "Never add a Co-authored-by trailer that names an AI model."
ADD_RULE = ["add", RULE, "--kind", "rule", "--area", "git", "--basis", "told", "--source", "s:1"]
HOOK = ("hooks", "install", "--agent", "generic")
TRAILER = "x\n\nCo-authored-by: Claude <noreply@anthropic.com>\n"

needs_config_hooks = pytest.mark.skipif(
    not githook.git_runs_config_hooks(), reason="this git has no config hooks"
)


def run(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def empty_commit(repo, message="x"):
    return run(repo, "commit", "-q", "--allow-empty", "-m", message)


@pytest.fixture
def tracked(repo, mem):
    folder = repo / ".githooks"
    folder.mkdir()
    (folder / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
    (folder / "pre-commit").chmod(0o755)
    git(repo, "add", ".githooks")
    git(repo, "commit", "-q", "-m", "team hooks")
    git(repo, "config", "core.hooksPath", ".githooks")
    return repo


def rename(repo, monkeypatch):
    new = repo.parent / "renamed"
    repo.rename(new)
    monkeypatch.chdir(new)
    return new


@needs_config_hooks
def test_the_stored_command_names_no_folder_of_this_machine(tracked, capsys):
    assert main(HOOK) == 0
    command = git(tracked, "config", "--local", "--get", "hook.cairnkit-pre-commit.command")
    assert str(tracked) not in command and str(tracked.resolve()) not in command


@needs_config_hooks
def test_a_rename_does_not_stop_a_commit_or_a_switch(tracked, capsys, monkeypatch):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    new = rename(tracked, monkeypatch)
    result = empty_commit(new)
    assert result.returncode == 0, result.stderr
    result = run(new, "switch", "-q", "-c", "topic")
    assert result.returncode == 0, result.stderr


@needs_config_hooks
def test_the_guard_still_works_after_a_rename(tracked, capsys, monkeypatch):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    new = rename(tracked, monkeypatch)
    assert empty_commit(new, TRAILER).returncode != 0


@needs_config_hooks
def test_a_copy_with_the_source_removed_still_commits(tracked, capsys, monkeypatch, tmp_path):
    assert main(HOOK) == 0
    copy = tmp_path / "copy"
    shutil.copytree(tracked, copy, symlinks=True)
    shutil.rmtree(tracked)
    monkeypatch.chdir(copy)
    result = empty_commit(copy)
    assert result.returncode == 0, result.stderr


@needs_config_hooks
def test_a_linked_worktree_runs_the_hooks_from_the_common_folder(tracked, capsys):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    worktree = add_worktree(tracked, "topic")
    assert empty_commit(worktree).returncode == 0
    assert empty_commit(worktree, TRAILER).returncode != 0


@needs_config_hooks
def test_check_is_true_after_a_rename(tracked, capsys, monkeypatch):
    assert main(HOOK) == 0
    rename(tracked, monkeypatch)
    capsys.readouterr()
    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert "git hooks: on, beside core.hooksPath .githooks" in out
    assert "does not run" not in out


def old_wiring(repo):
    """The absolute command of an earlier install."""
    for hook in githook.PERSONAL_HOOKS:
        git(
            repo,
            "config",
            "--local",
            f"hook.cairnkit-{hook}.command",
            str(repo / ".git" / "cairnkit-hooks" / hook),
        )


@needs_config_hooks
def test_session_start_heals_an_old_absolute_command(tracked, capsys, monkeypatch):
    assert main(HOOK) == 0
    old_wiring(tracked)
    new = rename(tracked, monkeypatch)
    assert empty_commit(new).returncode != 0, (
        "the old command must fail, or this test proves nothing"
    )
    assert main(["hook", "session-start", "--agent", "generic"]) == 0
    result = empty_commit(new)
    assert result.returncode == 0, result.stderr


@needs_config_hooks
def test_uninstall_removes_an_old_absolute_command(tracked, capsys):
    assert main(HOOK) == 0
    old_wiring(tracked)
    assert main(["hooks", "uninstall"]) == 0
    assert "hook.cairnkit" not in git(tracked, "config", "--local", "--list")


@needs_config_hooks
def test_check_says_that_an_old_command_needs_the_install(tracked, capsys):
    assert main(HOOK) == 0
    old_wiring(tracked)
    capsys.readouterr()
    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert "memory hooks install" in out
    assert "so git does not run" not in out


@pytest.fixture
def global_path(tmp_path, monkeypatch):
    folder = tmp_path / "global-hooks"
    folder.mkdir()
    config = tmp_path / "global-config"
    config.write_text(f"[core]\n\thooksPath = {folder}\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    return folder


def second_repo(tmp_path, name):
    other = tmp_path / name
    other.mkdir()
    git(other, "init", "-q", "-b", "main")
    git(other, "config", "user.name", "Test")
    git(other, "config", "user.email", "t@example.invalid")
    return other


@needs_config_hooks
def test_install_writes_nothing_in_a_folder_outside_the_repo(global_path, repo, mem, capsys):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    assert list(global_path.iterdir()) == []
    for hook in githook.PERSONAL_HOOKS:
        assert f"cairnkit-{hook}" in git(repo, "hook", "list", hook)
    assert githook.guard_installed(find_project(repo))


@needs_config_hooks
def test_the_guard_of_one_repo_does_not_reach_another(global_path, repo, mem, tmp_path, capsys):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    assert empty_commit(repo, TRAILER).returncode != 0
    other = second_repo(tmp_path, "unrelated")
    result = empty_commit(other, TRAILER)
    assert result.returncode == 0, result.stderr


@needs_config_hooks
def test_uninstall_in_one_repo_leaves_another_repo_alone(
    global_path, repo, mem, tmp_path, capsys, monkeypatch
):
    assert main(HOOK) == 0
    other = second_repo(tmp_path, "other")
    git(other, "commit", "-q", "--allow-empty", "-m", "first")
    monkeypatch.chdir(other)
    assert main(["init", "--no-default-rules"]) == 0
    assert main(HOOK) == 0
    monkeypatch.chdir(repo)
    assert main(["hooks", "uninstall"]) == 0
    monkeypatch.chdir(other)
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "git hooks: on" in capsys.readouterr().out


@needs_config_hooks
def test_the_summary_names_the_folder_of_this_repo(global_path, repo, mem, capsys, monkeypatch):
    from cairnkit import hooks_cmd

    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    capsys.readouterr()
    assert main(["init", "--no-default-rules"]) == 0
    out = capsys.readouterr().out
    assert "Git hooks installed in .git/cairnkit-hooks" in out
    assert "global-hooks" not in out


def test_an_older_git_says_the_hooks_are_off_and_writes_nothing_outside(
    global_path, repo, mem, capsys, monkeypatch
):
    monkeypatch.setattr(githook, "git_runs_config_hooks", lambda: False)
    capsys.readouterr()
    assert main(HOOK) == 0
    out = capsys.readouterr().out
    assert "does not run here" in out and "2.54" in out
    assert "points into the repo" not in out
    assert list(global_path.iterdir()) == []
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0
    assert "2.54" in capsys.readouterr().out


@needs_config_hooks
def test_an_old_block_in_a_global_folder_is_named_and_left_alone(global_path, repo, mem, capsys):
    path = global_path / "pre-commit"
    text = f"#!/bin/sh\n{githook.START}\n{githook.pre_commit_body()}{githook.END}\n"
    path.write_text(text)
    path.chmod(0o755)
    capsys.readouterr()
    assert main(HOOK) == 0
    assert str(path) in capsys.readouterr().out
    assert path.read_text() == text
    capsys.readouterr()
    assert main(["hooks", "uninstall"]) == 0
    assert str(path) in capsys.readouterr().out
    assert path.read_text() == text


def test_a_path_inside_the_git_folder_holds_the_hooks(repo, mem, capsys):
    folder = repo / ".git" / "my-hooks"
    folder.mkdir()
    git(repo, "config", "core.hooksPath", ".git/my-hooks")
    assert main(HOOK) == 0
    assert githook.holds_block((folder / "pre-commit").read_text())
    assert "hook.cairnkit" not in git(repo, "config", "--local", "--list")
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "git hooks: on" in capsys.readouterr().out


@needs_config_hooks
def test_unset_hooks_path_with_config_hooks_never_says_none(tracked, capsys):
    assert main(HOOK) == 0
    git(tracked, "config", "--unset", "core.hooksPath")
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "core.hooksPath None" not in capsys.readouterr().out
