"""The branch-note gate: real git commits and pushes in throwaway repos, through the real hooks."""

from __future__ import annotations

import os
import shlex
import subprocess

import pytest
from conftest import add_worktree, git

from cairnkit import githook, skills
from cairnkit.branchgate import SETTING, STATE_FILE
from cairnkit.cli import main

HOOK = ("hooks", "install", "--agent", "generic")
AGENT = {"CLAUDECODE": "1"}
needs_config_hooks = pytest.mark.skipif(
    not githook.git_runs_config_hooks(), reason="this git has no config hooks"
)


def run(repo, *args, env=None, stdin=None):
    full = {**os.environ, **(env if env is not None else AGENT)}
    return subprocess.run(
        ["git", *args], cwd=repo, env=full, input=stdin, capture_output=True, text=True, check=False
    )


def change(repo, *commit_args, env=None):
    with (repo / "work.txt").open("a") as handle:
        handle.write("x\n")
    git(repo, "add", "work.txt")
    return run(repo, "commit", "-q", "-m", "work", *commit_args, env=env)


def printed_add(result) -> list[str]:
    """The command that a refusal prints, as a tool's shell would split it."""
    line = next(ln for ln in result.stderr.splitlines() if ln.startswith("  memory add "))
    return shlex.split(line)[1:]


def add_note(text="Branch work: for the test; next: push"):
    assert main(["add", text, "--short"]) == 0


@pytest.fixture
def gated(repo, mem, capsys):
    assert main(HOOK) == 0
    git(repo, "config", "--local", SETTING, "true")
    git(repo, "checkout", "-q", "-b", "work")
    capsys.readouterr()
    return repo


@pytest.fixture
def remote(tmp_path, gated):
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    git(gated, "remote", "add", "origin", str(tmp_path / "remote.git"))
    assert run(gated, "push", "-q", "origin", "main", env={}).returncode == 0
    return tmp_path / "remote.git"


def test_it_is_off_until_the_local_setting_is_on(repo, mem, capsys):
    assert main(HOOK) == 0
    git(repo, "checkout", "-q", "-b", "work")
    assert change(repo).returncode == 0
    assert run(repo, "config", "--local", "--get", SETTING).returncode != 0


def test_a_first_commit_refuses_and_the_printed_command_fixes_it(gated, capsys):
    refused = change(gated)
    assert refused.returncode != 0
    assert "commit refused" in refused.stderr and "work" in refused.stderr
    argv = printed_add(refused)
    assert argv[0] == "add" and argv[-1] == "--short"
    assert main(argv) == 0
    assert run(gated, "commit", "-q", "-m", "work").returncode == 0


def test_a_later_commit_needs_nothing(gated):
    add_note()
    assert change(gated).returncode == 0
    assert change(gated).returncode == 0


def test_the_default_branch_is_not_gated(repo, mem, capsys):
    assert main(HOOK) == 0
    git(repo, "config", "--local", SETTING, "true")
    assert change(repo).returncode == 0


def test_a_person_is_never_refused(gated, remote):
    assert change(gated, env={}).returncode == 0
    assert run(gated, "push", "-q", "origin", "work", env={}).returncode == 0
    assert change(gated, env={}).returncode == 0
    assert run(gated, "push", "-q", "origin", "work", env={}).returncode == 0


@pytest.mark.parametrize("name", skills.AGENT_SHELL_MARKERS)
def test_each_tool_marker_counts_as_an_agent(gated, name):
    assert change(gated, env={name: "1"}).returncode != 0


@pytest.mark.parametrize(
    "name", ["CURSOR_TRACE_ID", "GROK_WORKSPACE_ROOT", "GROK_HOOK_EVENT", "VSCODE_PID", "AI_AGENT"]
)
def test_a_name_that_a_person_terminal_can_hold_lets_it_through(gated, name):
    assert change(gated, env={name: "1"}).returncode == 0


def test_a_first_push_needs_a_note_when_a_person_made_the_commit(gated, remote):
    assert change(gated, env={}).returncode == 0
    refused = run(gated, "push", "origin", "work")
    assert refused.returncode != 0 and "push refused" in refused.stderr
    assert main(printed_add(refused)) == 0
    assert run(gated, "push", "-q", "origin", "work").returncode == 0


def test_a_push_refuses_until_the_note_changed_since_the_last_push(gated, remote):
    add_note()
    assert change(gated).returncode == 0
    assert run(gated, "push", "-q", "origin", "work").returncode == 0
    assert change(gated).returncode == 0
    refused = run(gated, "push", "origin", "work")
    assert refused.returncode != 0 and "did not change" in refused.stderr
    assert main(printed_add(refused)) == 0
    assert run(gated, "push", "-q", "origin", "work").returncode == 0
    assert change(gated).returncode == 0
    assert run(gated, "push", "origin", "work").returncode != 0


@pytest.mark.parametrize("failure", ["dry run", "a later hook refuses"])
def test_a_push_that_did_not_land_does_not_count_as_the_last_push(gated, remote, failure):
    """Without this, the retry would read the same note as already pushed, and refuse."""
    add_note()
    assert change(gated).returncode == 0
    assert run(gated, "push", "-q", "origin", "work").returncode == 0
    add_note("Branch work: second step")
    assert change(gated).returncode == 0
    script = gated / ".git" / "hooks" / "pre-push"
    text = script.read_text()
    if failure == "dry run":
        assert run(gated, "push", "-q", "--dry-run", "origin", "work").returncode == 0
    else:
        script.write_text(text + "exit 1\n")
        assert run(gated, "push", "-q", "origin", "work").returncode != 0
        script.write_text(text)
    result = run(gated, "push", "-q", "origin", "work")
    assert result.returncode == 0, result.stderr
    assert change(gated).returncode == 0
    assert run(gated, "push", "origin", "work").returncode != 0, "that retry was the last push"


def test_a_rebase_and_a_force_push_with_no_new_patch_pass(gated, remote):
    add_note()
    assert change(gated).returncode == 0
    assert run(gated, "push", "-q", "origin", "work").returncode == 0
    git(gated, "checkout", "-q", "main")
    (gated / "other.txt").write_text("other\n")
    git(gated, "add", "other.txt")
    assert run(gated, "commit", "-q", "-m", "other", env={}).returncode == 0
    git(gated, "checkout", "-q", "work")
    assert run(gated, "rebase", "-q", "main").returncode == 0
    result = run(gated, "push", "-q", "--force", "origin", "work")
    assert result.returncode == 0, result.stderr


def test_a_merge_of_the_default_branch_and_its_push_pass(gated, remote):
    add_note()
    assert change(gated).returncode == 0
    assert run(gated, "push", "-q", "origin", "work").returncode == 0
    git(gated, "checkout", "-q", "main")
    (gated / "other.txt").write_text("other\n")
    git(gated, "add", "other.txt")
    assert run(gated, "commit", "-q", "-m", "other", env={}).returncode == 0
    git(gated, "checkout", "-q", "work")
    assert run(gated, "merge", "-q", "--no-ff", "--no-edit", "main").returncode == 0
    result = run(gated, "push", "-q", "origin", "work")
    assert result.returncode == 0, result.stderr


def conflict_on_first_commit(repo):
    """A conflict on a branch with no commit of its own, so that only the state lets it go."""
    git(repo, "checkout", "-q", "main")
    (repo / "c.txt").write_text("base\n")
    git(repo, "add", "c.txt")
    assert run(repo, "commit", "-q", "-m", "base", env={}).returncode == 0
    git(repo, "checkout", "-q", "-b", "side")
    (repo / "c.txt").write_text("side\n")
    git(repo, "add", "c.txt")
    assert run(repo, "commit", "-q", "-m", "side", env={}).returncode == 0
    git(repo, "checkout", "-q", "main")
    (repo / "c.txt").write_text("main\n")
    git(repo, "add", "c.txt")
    assert run(repo, "commit", "-q", "-m", "main", env={}).returncode == 0
    git(repo, "branch", "-f", "work", "main")
    git(repo, "checkout", "-q", "work")


def test_a_merge_with_a_conflict_is_not_trapped(gated):
    conflict_on_first_commit(gated)
    assert run(gated, "merge", "-q", "--no-edit", "side").returncode != 0
    (gated / "c.txt").write_text("done\n")
    git(gated, "add", "c.txt")
    result = run(gated, "commit", "-q", "--no-edit")
    assert result.returncode == 0, result.stderr


def test_a_cherry_pick_with_a_conflict_is_not_trapped(gated):
    conflict_on_first_commit(gated)
    assert run(gated, "cherry-pick", "side").returncode != 0
    (gated / "c.txt").write_text("done\n")
    git(gated, "add", "c.txt")
    result = run(gated, "commit", "-q", "--no-edit")
    assert result.returncode == 0, result.stderr


def test_a_rebase_with_a_conflict_is_not_trapped(gated):
    conflict_on_first_commit(gated)
    git(gated, "checkout", "-q", "side")
    assert run(gated, "rebase", "-q", "work").returncode != 0
    (gated / "c.txt").write_text("done\n")
    git(gated, "add", "c.txt")
    env = {**AGENT, "GIT_EDITOR": "true"}
    result = run(gated, "rebase", "--continue", env=env)
    assert result.returncode == 0, result.stderr


def test_an_amend_is_not_trapped_on_a_branch_with_no_commit_of_its_own(gated):
    result = change(gated, "--amend", "--no-edit")
    assert result.returncode == 0, result.stderr


def test_a_detached_head_is_not_gated(gated, remote):
    git(gated, "checkout", "-q", "--detach")
    assert change(gated).returncode == 0
    assert run(gated, "push", "-q", "origin", "HEAD:refs/heads/from-detached").returncode == 0


def test_a_repo_with_no_remote_gates_only_the_first_commit(gated):
    assert change(gated).returncode != 0
    add_note()
    assert run(gated, "commit", "-q", "-m", "work").returncode == 0
    assert run(gated, "remote").stdout == ""
    assert change(gated).returncode == 0


def test_a_repo_with_no_default_branch_lets_it_through(tmp_path, monkeypatch, capsys):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "trunk")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "commit", "-q", "--allow-empty", "-m", "init")
    monkeypatch.chdir(root)
    assert main(["init", "--no-default-rules"]) == 0
    assert main(HOOK) == 0
    git(root, "config", "--local", SETTING, "true")
    git(root, "checkout", "-q", "-b", "work")
    assert change(root).returncode == 0


def test_a_branch_from_a_fetched_tip_counts_its_first_commit(gated, remote):
    """The local default branch is behind, and the new branch starts from the remote's tip."""
    assert run(gated, "checkout", "-q", "main", env={}).returncode == 0
    (gated / "far.txt").write_text("far\n")
    git(gated, "add", "far.txt")
    assert run(gated, "commit", "-q", "-m", "far", env={}).returncode == 0
    assert run(gated, "push", "-q", "origin", "main", env={}).returncode == 0
    git(gated, "reset", "-q", "--hard", "HEAD~1")
    git(gated, "checkout", "-q", "-b", "fresh", "origin/main")
    refused = change(gated)
    assert refused.returncode != 0 and "fresh" in refused.stderr


def test_a_linked_worktree_keeps_one_state_and_commits_through_the_gate(
    gated, remote, capsys, monkeypatch
):
    other = add_worktree(gated, "second")
    refused = change(other)
    assert refused.returncode != 0 and "second" in refused.stderr
    monkeypatch.chdir(other)
    assert main(printed_add(refused)) == 0
    assert run(other, "commit", "-q", "-m", "work").returncode == 0
    assert run(other, "push", "-q", "origin", "second").returncode == 0
    assert (gated / ".git" / STATE_FILE).is_file()


def test_a_tag_and_a_branch_delete_are_not_gated(gated, remote):
    add_note()
    assert change(gated).returncode == 0
    git(gated, "tag", "v1")
    assert run(gated, "push", "-q", "origin", "v1").returncode == 0
    assert run(gated, "push", "-q", "origin", "work").returncode == 0
    assert run(gated, "push", "-q", "origin", ":work").returncode == 0


def test_it_writes_nothing_that_git_tracks(gated, remote):
    add_note()
    assert change(gated).returncode == 0
    assert run(gated, "push", "-q", "origin", "work").returncode == 0
    assert git(gated, "status", "--porcelain").strip() == ""
    assert (gated / ".git" / STATE_FILE).is_file()


def test_a_broken_state_file_lets_the_push_through(gated, remote):
    add_note()
    assert change(gated).returncode == 0
    (gated / ".git" / STATE_FILE).write_text("{not json")
    assert run(gated, "push", "-q", "origin", "work").returncode == 0


def test_the_guard_and_a_later_hook_still_read_the_ref_list(gated, remote):
    add_note()
    assert change(gated).returncode == 0
    script = gated / ".git" / "hooks" / "pre-push"
    script.write_text(script.read_text() + 'cat > "$(git rev-parse --git-dir)/refs-seen"\n')
    assert run(gated, "push", "-q", "origin", "work").returncode == 0
    assert "refs/heads/work" in (gated / ".git" / "refs-seen").read_text()


def test_the_fix_commit_file_runs_through_the_gate(repo, mem, capsys, tmp_path):
    rule = "Never add a Co-authored-by trailer that names an AI model."
    args = ["add", rule, "--kind", "rule", "--area", "git", "--basis", "told", "--source", "s:1"]
    assert main(args) == 0
    assert main(HOOK) == 0
    git(repo, "config", "--local", SETTING, "true")
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
    assert run(repo, "push", "-q", "origin", "main", env={}).returncode == 0
    git(repo, "checkout", "-q", "-b", "work")
    add_note()
    assert change(repo).returncode == 0
    tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    message = "Fix\n\nCo-authored-by: Claude <noreply@anthropic.com>"
    sha = run(repo, "commit-tree", tree, "-p", "HEAD", "-m", message).stdout.strip()
    git(repo, "update-ref", "HEAD", sha)
    assert run(repo, "push", "origin", "work").returncode != 0
    fix = run(
        repo,
        "rebase",
        "--exec",
        'sh "$(git rev-parse --git-common-dir)/cairnkit-fix-commit"',
        "main",
    )
    assert fix.returncode == 0, fix.stderr
    result = run(repo, "push", "-q", "origin", "work")
    assert result.returncode == 0, result.stderr


def test_the_fix_commit_file_on_a_branch_with_no_commit_of_its_own_is_not_trapped(
    repo, mem, capsys
):
    rule = "Never add a Co-authored-by trailer that names an AI model."
    args = ["add", rule, "--kind", "rule", "--area", "git", "--basis", "told", "--source", "s:1"]
    assert main(args) == 0
    assert main(HOOK) == 0
    git(repo, "config", "--local", SETTING, "true")
    tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    message = "Fix\n\nCo-authored-by: Claude <noreply@anthropic.com>"
    sha = run(repo, "commit-tree", tree, "-p", "HEAD", "-m", message).stdout.strip()
    git(repo, "update-ref", "HEAD", sha)
    git(repo, "checkout", "-q", "-b", "work")
    fix = run(repo, "rev-parse", "--git-common-dir").stdout.strip()
    done = subprocess.run(
        ["sh", f"{fix}/cairnkit-fix-commit"],
        cwd=repo,
        env={**os.environ, **AGENT},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


@needs_config_hooks
def test_under_a_tracked_hooks_path_it_runs_beside_the_folder_and_changes_nothing(
    repo, mem, capsys, tmp_path
):
    (repo / ".git" / "info" / "exclude").write_text("memory-bank\n")
    folder = repo / ".githooks"
    folder.mkdir()
    (folder / "pre-commit").write_text("#!/bin/sh\n")
    (folder / "pre-commit").chmod(0o755)
    git(repo, "add", ".githooks")
    assert run(repo, "commit", "-q", "-m", "team hooks", env={}).returncode == 0
    git(repo, "config", "core.hooksPath", ".githooks")
    assert main(HOOK) == 0
    git(repo, "config", "--local", SETTING, "true")
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    git(repo, "remote", "add", "origin", str(tmp_path / "remote.git"))
    assert run(repo, "push", "-q", "origin", "main", env={}).returncode == 0
    git(repo, "checkout", "-q", "-b", "work")
    refused = change(repo)
    assert refused.returncode != 0 and "commit refused" in refused.stderr
    assert main(printed_add(refused)) == 0
    assert run(repo, "commit", "-q", "-m", "work").returncode == 0
    assert run(repo, "push", "-q", "origin", "work").returncode == 0
    assert change(repo).returncode == 0
    assert "did not change" in run(repo, "push", "origin", "work").stderr
    assert git(repo, "status", "--porcelain").strip() == ""
    assert sorted(p.name for p in folder.iterdir()) == ["pre-commit"]
    assert git(repo, "config", "core.hooksPath").strip() == ".githooks"


def test_uninstall_takes_back_the_setting_and_the_state(gated, remote, capsys):
    add_note()
    assert change(gated).returncode == 0
    assert run(gated, "push", "-q", "origin", "work").returncode == 0
    assert main(["hooks", "uninstall"]) == 0
    assert not (gated / ".git" / STATE_FILE).exists()
    assert run(gated, "config", "--local", "--get", SETTING).returncode != 0
