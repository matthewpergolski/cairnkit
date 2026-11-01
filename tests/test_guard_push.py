"""The push guard never traps a person. Real commits, real pushes, and each printed fix run as is.

The identities and lines here name AI tools on purpose. They are fixtures that the guard must see.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest
from conftest import git

from cairnkit import githook
from cairnkit.cli import main

RULE = "Never add a Co-authored-by trailer that names an AI model."
ADD_RULE = ["add", RULE, "--kind", "rule", "--area", "git", "--basis", "told", "--source", "s:1"]
HOOK = ("hooks", "install", "--agent", "generic")
AI = ("Cursor Agent", "cursoragent@cursor.com")
PAL = ("Pat Lee", "pat@example.com")
TRAILER = "Fix\n\nCo-authored-by: Claude <noreply@anthropic.com>"


def who_env(author=None, committer=None):
    env = dict(os.environ)
    if author:
        env |= {"GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1]}
    if committer:
        env |= {"GIT_COMMITTER_NAME": committer[0], "GIT_COMMITTER_EMAIL": committer[1]}
    return env


def run(repo, *args, env=None, stdin=None):
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, input=stdin, capture_output=True, text=True, check=False
    )


def tree_commit(repo, message="skipped the hook", author=None, committer=None):
    """A commit that never ran commit-msg, as a rebase or a tool's plumbing can make."""
    tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    sha = run(
        repo, "commit-tree", tree, "-p", "HEAD", "-m", message, env=who_env(author, committer)
    ).stdout.strip()
    git(repo, "update-ref", "HEAD", sha)
    return sha


def file_commit(repo, message, author=None, committer=None):
    with (repo / "f.txt").open("a") as fh:
        fh.write("x\n")
    git(repo, "add", "f.txt")
    result = run(
        repo, "commit", "-q", "-F", "-", stdin=message, env=who_env(author, committer or author)
    )
    assert result.returncode == 0, result.stderr
    return git(repo, "rev-parse", "HEAD").strip()


def guard_on(capsys):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    capsys.readouterr()


@pytest.fixture
def remote(tmp_path):
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    return tmp_path / "remote.git"


def remote_head(remote, ref="refs/heads/main"):
    return run(remote, "rev-parse", "--verify", "-q", ref).stdout.strip()


@pytest.fixture
def old_history(repo, mem, capsys):
    tree_commit(repo, author=AI)
    tree_commit(repo, TRAILER)
    guard_on(capsys)
    return repo


def test_a_first_push_of_old_ai_commits_passes_with_a_count(old_history, remote):
    result = run(old_history, "push", str(remote), "main")
    assert result.returncode == 0, result.stderr
    assert remote_head(remote) == git(old_history, "rev-parse", "HEAD").strip()
    assert "2 older commit(s)" in result.stderr


def test_a_second_push_does_not_count_again(old_history, remote):
    git(old_history, "remote", "add", "origin", str(remote))
    assert run(old_history, "push", "origin", "main").returncode == 0
    tree_commit(old_history)
    assert "older commit" not in run(old_history, "push", "origin", "main").stderr


@pytest.mark.parametrize("push", [("v1",), ("--tags",)], ids=["tag", "tags"])
def test_a_tag_on_old_ai_commits_pushes(repo, mem, capsys, remote, push):
    tree_commit(repo, author=AI)
    git(repo, "tag", "-a", "v1", "-m", "one")
    guard_on(capsys)
    result = run(repo, "push", str(remote), *push)
    assert result.returncode == 0, result.stderr
    assert "1 older commit(s)" in result.stderr


def test_a_branch_from_before_the_guard_pushes(repo, mem, capsys, remote):
    git(repo, "branch", "old")
    git(repo, "switch", "-q", "old")
    tree_commit(repo, author=AI)
    git(repo, "switch", "-q", "main")
    guard_on(capsys)
    assert run(repo, "push", str(remote), "old").returncode == 0


def test_a_new_commit_on_old_history_is_still_refused(old_history, remote):
    sha = tree_commit(old_history, author=AI)
    result = run(old_history, "push", str(remote), "main")
    assert result.returncode != 0
    assert sha[:7] in result.stderr
    assert remote_head(remote) == ""


def test_a_commit_rewritten_after_the_guard_counts_as_new(old_history, remote):
    git(old_history, "reset", "-q", "--hard", "HEAD~1")
    tree_commit(old_history, TRAILER)
    assert run(old_history, "push", str(remote), "main").returncode != 0


def test_a_shallow_clone_does_not_refuse_what_it_cannot_see(repo, mem, capsys, tmp_path, remote):
    for message in ("a", TRAILER, TRAILER, "b"):
        tree_commit(repo, message, author=AI if message == "b" else None)
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth=2", f"file://{repo}", str(clone)],
        check=True,
        capture_output=True,
    )
    git(clone, "config", "user.name", "Test")
    git(clone, "config", "user.email", "test@example.com")
    git(clone, "remote", "remove", "origin")
    git(remote, "config", "receive.shallowUpdate", "true")
    cwd = os.getcwd()
    os.chdir(clone)
    try:
        assert main(["init", "--no-default-rules"]) == 0
        guard_on(capsys)
    finally:
        os.chdir(cwd)
    file_commit(clone, "mine")
    result = run(clone, "push", str(remote), "HEAD:refs/heads/main")
    assert result.returncode == 0, result.stderr


def test_a_fetched_shallow_tip_with_no_ref_is_not_refused_at_its_edge(
    repo, mem, capsys, tmp_path, remote
):
    guard_on(capsys)
    upstream = tmp_path / "upstream"
    git(tmp_path, "init", "-q", "-b", "main", str(upstream))
    git(upstream, "config", "user.name", "Test")
    git(upstream, "config", "user.email", "test@example.com")
    (upstream / "u.txt").write_text("u\n")
    git(upstream, "add", "u.txt")
    run(upstream, "commit", "-q", "-m", "edge", env=who_env(AI))
    git(remote, "config", "receive.shallowUpdate", "true")
    git(repo, "fetch", "-q", "--depth=1", f"file://{upstream}", "main")
    git(repo, "switch", "-qc", "there", "FETCH_HEAD")
    result = run(repo, "push", str(remote), "HEAD:refs/heads/there")
    assert result.returncode == 0, result.stderr


@pytest.fixture
def pushed(repo, mem, capsys, remote):
    guard_on(capsys)
    git(repo, "remote", "add", "origin", str(remote))
    assert run(repo, "push", "-q", "origin", "main").returncode == 0
    return repo


def contributor_clone(tmp_path, remote):
    other = tmp_path / "pal"
    git(tmp_path, "clone", "-q", "-b", "main", str(remote), str(other))
    return other


def test_a_contributors_merged_commit_passes_and_its_trailer_is_named(pushed, remote, tmp_path):
    other = contributor_clone(tmp_path, remote)
    plain = file_commit(other, "Pat's fix", author=PAL)
    trailed = file_commit(other, TRAILER, author=PAL)
    git(pushed, "pull", "-q", "--no-rebase", str(other), "main")
    result = run(pushed, "push", "origin", "main")
    assert result.returncode == 0, result.stderr
    assert trailed[:7] in result.stderr
    assert "Co-authored-by: Claude" in result.stderr
    assert plain[:7] not in result.stderr
    assert "under the owner's name" not in result.stderr


def test_a_trailer_i_committed_is_refused(pushed):
    tree_commit(pushed, TRAILER)
    assert run(pushed, "push", "origin", "main").returncode != 0


def test_an_ai_committer_is_refused_with_a_person_as_author(pushed):
    tree_commit(pushed, author=PAL, committer=AI)
    assert run(pushed, "push", "origin", "main").returncode != 0


def test_an_ai_author_is_refused_with_a_contributor_as_committer(pushed):
    tree_commit(pushed, author=AI, committer=PAL)
    assert run(pushed, "push", "origin", "main").returncode != 0


def test_a_pruned_commit_in_the_base_does_not_trap(repo, mem, capsys, remote):
    git(repo, "switch", "-qc", "gone")
    file_commit(repo, "soon gone")
    guard_on(capsys)
    git(repo, "switch", "-q", "main")
    git(repo, "branch", "-qD", "gone")
    git(repo, "reflog", "expire", "--expire=now", "--all")
    git(repo, "gc", "-q", "--prune=now")
    tree_commit(repo, author=AI)
    assert run(repo, "push", str(remote), "main").returncode != 0
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    assert run(repo, "push", str(remote), "main").returncode == 0


def test_a_lost_base_is_recorded_again_and_does_not_trap(old_history, remote):
    (old_history / ".git" / githook.BASE_FILE).unlink()
    assert run(old_history, "push", str(remote), "main").returncode == 0
    assert (old_history / ".git" / githook.BASE_FILE).is_file()
    tree_commit(old_history, author=AI)
    assert run(old_history, "push", str(remote), "main").returncode != 0


def test_the_base_goes_with_the_guard_and_the_next_guard_starts_a_new_one(old_history, remote):
    path = old_history / ".git" / githook.BASE_FILE
    assert path.is_file()
    assert main(["hooks", "uninstall"]) == 0
    assert not path.exists()
    sha = tree_commit(old_history, author=AI)
    assert main(HOOK) == 0
    assert sha in path.read_text()
    assert run(old_history, "push", str(remote), "main").returncode == 0


def test_a_second_install_keeps_the_base(old_history, remote):
    before = (old_history / ".git" / githook.BASE_FILE).read_text()
    tree_commit(old_history, author=AI)
    assert main(HOOK) == 0
    assert (old_history / ".git" / githook.BASE_FILE).read_text() == before
    assert run(old_history, "push", str(remote), "main").returncode != 0


def test_the_base_works_from_a_linked_worktree(old_history, remote, tmp_path):
    other = tmp_path / "linked"
    git(old_history, "worktree", "add", "-q", "-b", "linked", str(other))
    assert run(other, "push", str(remote), "linked").returncode == 0
    tree_commit(other, author=AI)
    assert run(other, "push", str(remote), "linked").returncode != 0


@pytest.mark.parametrize("shell", ["bash", "zsh", "dash"])
def test_each_shell_runs_the_check(repo, mem, capsys, remote, shell):
    found = shutil.which(shell)
    if found is None:
        pytest.skip(f"no {shell} here")
    path = repo / ".git" / "hooks" / "pre-push"
    path.write_text(f"#!{found}\ncat > /dev/null\n")
    path.chmod(0o755)
    tree_commit(repo, TRAILER)
    tree_commit(repo, author=AI)
    guard_on(capsys)
    result = run(repo, "push", str(remote), "main")
    assert result.returncode == 0, result.stderr
    assert "2 older commit(s)" in result.stderr
    bad = tree_commit(repo, author=AI)
    tree_commit(repo, TRAILER)
    refused = run(repo, "push", str(remote), "main")
    assert refused.returncode != 0
    assert bad[:7] in refused.stderr
    assert "git rebase" in refused.stderr


def printed(stderr: str, start: str) -> str:
    return next(line.strip() for line in stderr.splitlines() if line.strip().startswith(start))


def run_printed(repo, command, editor="true"):
    env = dict(os.environ, GIT_EDITOR=editor)
    return subprocess.run(
        ["sh", "-c", command], cwd=repo, env=env, capture_output=True, text=True, check=False
    )


@pytest.fixture
def strip_editor(tmp_path):
    path = tmp_path / "strip.sh"
    path.write_text('#!/bin/sh\ngrep -v Co-authored-by "$1" > "$1.t"; mv "$1.t" "$1"\n')
    path.chmod(0o755)
    return str(path)


def test_the_refusal_prints_each_way_out_and_never_the_skip_flag(pushed):
    tree_commit(pushed, author=AI)
    result = run(pushed, "push", "origin", "main")
    assert "--no-verify" not in result.stderr
    assert "git commit --amend" in result.stderr
    assert "git rebase" in result.stderr
    assert "[commit_msg_guard]" in result.stderr
    assert "hashes" in result.stderr


def test_the_printed_amend_fixes_a_trailer_on_an_empty_commit(pushed, remote, strip_editor):
    tree_commit(pushed, TRAILER)
    refused = run(pushed, "push", "origin", "main")
    done = run_printed(pushed, printed(refused.stderr, "git commit --amend"), strip_editor)
    assert done.returncode == 0, done.stderr
    assert "Co-authored-by" not in git(pushed, "log", "-1", "--format=%B")
    assert run(pushed, "push", "origin", "main").returncode == 0


def test_the_printed_amend_fixes_an_ai_author(pushed, remote):
    tree_commit(pushed, author=AI)
    refused = run(pushed, "push", "origin", "main")
    done = run_printed(pushed, printed(refused.stderr, "git commit --amend"))
    assert done.returncode == 0, done.stderr
    assert git(pushed, "log", "-1", "--format=%an").strip() == "Test"
    assert run(pushed, "push", "origin", "main").returncode == 0


def test_the_printed_rebase_fixes_a_root_an_empty_commit_and_a_trailer(repo, mem, capsys, remote):
    guard_on(capsys)
    git(repo, "checkout", "-q", "--orphan", "fresh")
    tree = git(repo, "write-tree").strip()
    root = run(repo, "commit-tree", tree, "-m", TRAILER, env=who_env(AI)).stdout.strip()
    git(repo, "update-ref", "refs/heads/fresh", root)
    git(repo, "reset", "-q", "--hard", root)
    tree_commit(repo, "Empty with a line\n\nMade-with: Cursor")
    file_commit(repo, "Pat's work", author=PAL)
    file_commit(repo, "plain mine")
    tree_commit(repo, "Only an AI author", author=AI)
    refused = run(repo, "push", str(remote), "fresh")
    assert refused.returncode != 0
    command = printed(refused.stderr, "git rebase")
    assert "--root" in command
    done = run_printed(repo, command)
    assert done.returncode == 0, done.stderr + done.stdout
    assert git(repo, "log", "--format=%an|%s").strip().splitlines() == [
        "Test|Only an AI author",
        "Test|plain mine",
        "Pat Lee|Pat's work",
        "Test|Empty with a line",
        "Test|Fix",
    ]
    assert "Co-authored-by" not in git(repo, "log", "--format=%B")
    assert "Made-with" not in git(repo, "log", "--format=%B")
    assert run(repo, "push", str(remote), "fresh").returncode == 0


def test_the_printed_rebase_starts_at_the_parent_and_leaves_older_hashes(pushed, remote):
    keep = file_commit(pushed, "mine, not pushed yet")
    tree_commit(pushed, TRAILER)
    file_commit(pushed, "later")
    refused = run(pushed, "push", "origin", "main")
    command = printed(refused.stderr, "git rebase")
    assert "--root" not in command
    done = run_printed(pushed, command)
    assert done.returncode == 0, done.stderr
    assert git(pushed, "rev-parse", "HEAD~2").strip() == keep
    assert run(pushed, "push", "origin", "main").returncode == 0


def test_the_printed_rebase_keeps_a_merge(pushed, remote):
    git(pushed, "switch", "-qc", "side")
    file_commit(pushed, "side work")
    git(pushed, "switch", "-q", "main")
    (pushed / "m.txt").write_text("m\n")
    git(pushed, "add", "m.txt")
    run(pushed, "commit", "-qm", "main work")
    git(pushed, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    tree_commit(pushed, TRAILER)
    refused = run(pushed, "push", "origin", "main")
    done = run_printed(pushed, printed(refused.stderr, "git rebase"))
    assert done.returncode == 0, done.stderr
    assert git(pushed, "rev-list", "--merges", "--count", "HEAD").strip() == "1"
    assert run(pushed, "push", "origin", "main").returncode == 0


def test_the_printed_rebase_works_from_a_linked_worktree(old_history, remote, tmp_path):
    other = tmp_path / "linked"
    git(old_history, "worktree", "add", "-q", "-b", "linked", str(other))
    tree_commit(other, TRAILER)
    refused = run(other, "push", str(remote), "linked")
    assert refused.returncode != 0
    done = run_printed(other, printed(refused.stderr, "git rebase"))
    assert done.returncode == 0, done.stderr
    assert run(other, "push", str(remote), "linked").returncode == 0


def test_the_printed_config_is_an_override_that_works(pushed, mem, remote):
    tree_commit(pushed, author=AI)
    tree_commit(pushed, TRAILER)
    refused = run(pushed, "push", "origin", "main")
    found = re.search(r"\[commit_msg_guard\]\n(?:\s*.*patterns = .*\n)+", refused.stderr)
    assert found
    block = "\n".join(line.strip() for line in found[0].splitlines())
    cfg = pushed / "memory-bank" / "config.toml"
    cfg.write_text(cfg.read_text() + "\n" + block + "\n")
    assert "`memory hooks install`" in refused.stderr
    assert main(HOOK) == 0
    assert run(pushed, "push", "origin", "main").returncode == 0
    assert run(pushed, "commit", "--allow-empty", "-qm", TRAILER).returncode == 0
    assert main(["check"]) == 0


def test_the_fix_step_leaves_a_clean_commit_alone(pushed):
    sha = file_commit(pushed, "clean")
    hook = pushed / ".git" / "hooks" / "pre-push"
    done = subprocess.run(
        ["sh", str(hook), "cairnkit-fix-commit"],
        cwd=pushed,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert git(pushed, "rev-parse", "HEAD").strip() == sha
