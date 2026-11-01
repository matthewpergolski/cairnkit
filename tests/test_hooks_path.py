"""Hooks under core.hooksPath: git runs them beside a tracked folder, and check says so.

The attribution lines and identities here are fixtures that the guard must refuse.
"""

from __future__ import annotations

import os
import subprocess

import pytest
from conftest import add_worktree, git

from cairnkit import githook, refresh
from cairnkit.cli import main
from cairnkit.paths import find_project

RULE = "Never add a Co-authored-by trailer that names an AI model."
ADD_RULE = ["add", RULE, "--kind", "rule", "--area", "git", "--basis", "told", "--source", "s:1"]
HOOK = ("hooks", "install", "--agent", "generic")
AI = ("Cursor Agent", "cursoragent@cursor.com")
HUMAN = ("Cursor Smith", "cursor.smith@example.com")
HOOKS = ("pre-commit", "post-checkout", "pre-push", "post-merge")

needs_config_hooks = pytest.mark.skipif(
    not githook.git_runs_config_hooks(), reason="this git has no config hooks"
)


def run(repo, *args, env=None, stdin=None):
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, input=stdin, capture_output=True, text=True, check=False
    )


def script(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def commit(repo, message="change", author=None, extra=()):
    with (repo / "f.txt").open("a") as fh:
        fh.write("x\n")
    git(repo, "add", "f.txt")
    env = dict(os.environ)
    if author:
        env |= {"GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1]}
    return run(repo, "commit", "-q", "-F", "-", *extra, stdin=message, env=env)


@pytest.fixture
def tracked(repo, mem):
    """A repo whose team hooks are tracked in .githooks. They log to an ignored file."""
    (repo / ".git" / "info" / "exclude").write_text("team.log\nmemory-bank\n")
    for name in ("commit-msg", "pre-push", "pre-commit"):
        script(repo / ".githooks" / name, f"#!/bin/sh\necho team-{name} >> team.log\n")
    git(repo, "add", ".githooks")
    git(repo, "commit", "-q", "-m", "team hooks")
    git(repo, "config", "core.hooksPath", ".githooks")
    return repo


def team_log(repo):
    path = repo / "team.log"
    return path.read_text().split() if path.exists() else []


@needs_config_hooks
def test_install_runs_the_hooks_beside_a_tracked_folder(tracked, capsys):
    before = {p.name: p.read_text() for p in (tracked / ".githooks").iterdir()}
    assert main(HOOK) == 0
    assert {p.name: p.read_text() for p in (tracked / ".githooks").iterdir()} == before
    assert git(tracked, "status", "--porcelain").strip() == ""
    assert git(tracked, "config", "core.hooksPath").strip() == ".githooks"
    for hook in HOOKS:
        assert f"cairnkit-{hook}" in git(tracked, "hook", "list", hook)


@needs_config_hooks
def test_the_memory_guard_and_the_team_hook_both_run(tracked, capsys):
    assert main(HOOK) == 0
    git(tracked, "add", "-f", "memory-bank")
    assert run(tracked, "commit", "-q", "-m", "leak").returncode != 0
    assert "team-pre-commit" in team_log(tracked)
    git(tracked, "reset", "-q")
    assert commit(tracked).returncode == 0
    assert team_log(tracked).count("team-commit-msg") == 1


@needs_config_hooks
def test_a_failing_team_hook_still_stops_the_commit(tracked, capsys):
    assert main(HOOK) == 0
    script(tracked / ".githooks" / "commit-msg", "#!/bin/sh\nexit 1\n")
    assert commit(tracked).returncode != 0


@needs_config_hooks
def test_the_attribution_guard_runs_at_commit_and_push(tracked, capsys, tmp_path):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    assert commit(tracked, author=AI).returncode != 0
    assert commit(tracked, "x\n\nGenerated with Claude Code\n").returncode != 0
    assert commit(tracked, author=HUMAN).returncode == 0
    git(tmp_path, "init", "-q", "--bare", "r.git")
    git(tracked, "remote", "add", "origin", str(tmp_path / "r.git"))
    assert run(tracked, "push", "-q", "origin", "main").returncode == 0
    tree = git(tracked, "rev-parse", "HEAD^{tree}").strip()
    env = {**os.environ, "GIT_AUTHOR_NAME": AI[0], "GIT_AUTHOR_EMAIL": AI[1]}
    sha = run(tracked, "commit-tree", tree, "-p", "HEAD", "-m", "plumbing", env=env).stdout.strip()
    git(tracked, "update-ref", "HEAD", sha)
    result = run(tracked, "push", "origin", "main")
    assert result.returncode != 0
    assert "Cursor Agent" in result.stderr
    assert "team-pre-push" in team_log(tracked)


@needs_config_hooks
def test_a_new_worktree_gets_its_link_through_the_config_hook(tracked, capsys):
    assert main(HOOK) == 0
    worktree = add_worktree(tracked, "topic")
    assert (worktree / "memory-bank").is_symlink()


@needs_config_hooks
def test_a_repo_path_with_a_space_works(tmp_path, monkeypatch, capsys):
    root = tmp_path / "my proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "t@example.invalid")
    script(root / ".githooks" / "commit-msg", "#!/bin/sh\nexit 0\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    git(root, "config", "core.hooksPath", ".githooks")
    monkeypatch.chdir(root)
    assert main(["init", "--no-default-rules"]) == 0
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    assert commit(root, author=AI).returncode != 0
    assert commit(root, author=HUMAN).returncode == 0


@needs_config_hooks
def test_a_second_install_changes_nothing(tracked, capsys):
    assert main(HOOK) == 0
    config = (tracked / ".git" / "config").read_text()
    capsys.readouterr()
    assert main(HOOK) == 0
    assert (tracked / ".git" / "config").read_text() == config
    assert "Already installed" in capsys.readouterr().out


@needs_config_hooks
def test_a_dry_run_writes_nothing(tracked, capsys):
    config = (tracked / ".git" / "config").read_text()
    assert main([*HOOK, "--dry-run"]) == 0
    assert (tracked / ".git" / "config").read_text() == config
    assert not (tracked / ".git" / "cairnkit-hooks").exists()


@needs_config_hooks
def test_uninstall_removes_the_config_and_the_files_and_keeps_the_path(tracked, capsys):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    assert main(["hooks", "uninstall"]) == 0
    assert "hook.cairnkit" not in git(tracked, "config", "--local", "--list")
    assert not (tracked / ".git" / "cairnkit-hooks").exists()
    assert git(tracked, "config", "core.hooksPath").strip() == ".githooks"
    assert commit(tracked, author=AI).returncode == 0


@needs_config_hooks
def test_refresh_rewrites_the_hooks_beside_the_folder(tracked, capsys):
    assert main(HOOK) == 0
    path = tracked / ".git" / "cairnkit-hooks" / "pre-push"
    path.write_text(path.read_text().replace("hook pre-push", "hook old-body"))
    assert main(["init", "--refresh"]) == 0
    assert "hook pre-push" in path.read_text()


@needs_config_hooks
def test_unsetting_the_path_moves_the_hooks_home_with_no_double_run(tracked, capsys):
    assert main(HOOK) == 0
    git(tracked, "config", "--unset", "core.hooksPath")
    assert main(HOOK) == 0
    assert "hook.cairnkit" not in git(tracked, "config", "--local", "--list")
    assert not (tracked / ".git" / "cairnkit-hooks").exists()
    assert githook.holds_block((tracked / ".git" / "hooks" / "pre-commit").read_text())


@needs_config_hooks
def test_setting_the_path_later_is_warned_about_and_then_healed(repo, mem, capsys):
    assert main(HOOK) == 0
    script(repo / ".githooks" / "pre-commit", "#!/bin/sh\nexit 0\n")
    git(repo, "config", "core.hooksPath", ".githooks")
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "warning: core.hooksPath is .githooks" in out
    assert "memory hooks install" in out
    line = refresh.repo_line(find_project(), None)
    assert line and "memory hooks install" in line
    assert main(HOOK) == 0
    assert not githook.holds_block((repo / ".git" / "hooks" / "pre-commit").read_text() + " ")
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "warning" not in out
    assert "git hooks: on, beside core.hooksPath .githooks" in out
    assert refresh.repo_line(find_project(), None) is None


def test_check_reports_hooks_that_run(repo, mem, capsys):
    assert main(HOOK) == 0
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "git hooks: on (.git/hooks)" in capsys.readouterr().out


def test_status_reports_the_hook_state(repo, mem, capsys):
    assert main(HOOK) == 0
    capsys.readouterr()
    assert main(["status"]) == 0
    assert "git hooks: on (.git/hooks)" in capsys.readouterr().out


def test_check_says_when_no_hooks_are_installed(repo, mem, capsys):
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "git hooks: not installed" in out
    assert "warning" not in out


def test_check_says_when_one_hook_is_gone(repo, mem, capsys):
    assert main(HOOK) == 0
    (repo / ".git" / "hooks" / "pre-push").unlink()
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "pre-push" in capsys.readouterr().out


def test_a_path_outside_the_repo_holds_the_hooks(repo, mem, capsys, tmp_path):
    folder = tmp_path / "shared-hooks"
    folder.mkdir()
    git(repo, "config", "core.hooksPath", str(folder))
    assert main(HOOK) == 0
    assert githook.holds_block((folder / "pre-commit").read_text())
    capsys.readouterr()
    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert f"git hooks: on ({folder})" in out
    assert "warning" not in out


def test_an_older_git_skips_and_says_why(tracked, capsys, monkeypatch):
    monkeypatch.setattr(githook, "git_runs_config_hooks", lambda: False)
    config = (tracked / ".git" / "config").read_text()
    assert main(HOOK) == 0
    out = capsys.readouterr().out
    assert "does not run here" in out
    assert "2.54" in out
    assert (tracked / ".git" / "config").read_text() == config
    assert git(tracked, "status", "--porcelain").strip() == ""
    assert main(["check", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "warning: core.hooksPath is .githooks" in out
    assert "2.54" in out
    assert refresh.repo_line(find_project(), None) is None


@needs_config_hooks
def test_a_tracked_hook_that_already_runs_memory_gets_no_second_run(tracked, capsys):
    script(
        tracked / ".githooks" / "pre-commit",
        f"#!/bin/sh\n{githook.START}\n{githook.pre_commit_body()}{githook.END}\n",
    )
    capsys.readouterr()
    assert main(HOOK) == 0
    assert "cairnkit-pre-commit" not in run(tracked, "hook", "list", "pre-commit").stdout


LAYOUTS = ["plain .git/hooks", "core.hooksPath .githooks"]


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_real_commit_table(repo, mem, capsys, layout):
    if layout != LAYOUTS[0]:
        if not githook.git_runs_config_hooks():
            pytest.skip("this git has no config hooks")
        script(repo / ".githooks" / "commit-msg", "#!/bin/sh\nexit 0\n")
        git(repo, "add", ".githooks")
        git(repo, "commit", "-q", "-m", "team hooks")
        git(repo, "config", "core.hooksPath", ".githooks")
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0

    def amend(*extra):
        return run(repo, "commit", "--amend", "-q", "--no-edit", *extra)

    rows = [
        (
            "trailer",
            False,
            lambda: commit(repo, "x\n\nCo-authored-by: Claude <noreply@anthropic.com>\n"),
        ),
        ("generator line", False, lambda: commit(repo, "x\n\nGenerated with Claude Code\n")),
        ("Made-with line", False, lambda: commit(repo, "x\n\nMade-with: Cursor\n")),
        ("AI author", False, lambda: commit(repo, author=AI)),
        ("human named Cursor Smith", True, lambda: commit(repo, author=HUMAN)),
        ("human plain", True, lambda: commit(repo, author=("Jane Doe", "jane@example.com"))),
        ("amend, human", True, lambda: amend()),
        ("amend to AI author", False, lambda: amend("--author=Cursor Agent <c@example.com>")),
        ("amend to bot address", False, lambda: amend("--author=Jane <cursoragent@cursor.com>")),
    ]
    wrong = []
    with capsys.disabled():
        print(f"\n| {layout} | case | expected | result | exit |")
    for name, passes, act in rows:
        result = act()
        git(repo, "reset", "-q")
        with capsys.disabled():
            want = "accepted" if passes else "refused"
            got = "accepted" if result.returncode == 0 else "refused"
            print(f"| {layout} | {name} | {want} | {got} | {result.returncode} |")
        if (result.returncode == 0) != passes:
            wrong.append(name)
    assert wrong == []
