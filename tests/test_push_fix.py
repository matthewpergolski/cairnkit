"""A refused push prints a fix that can touch only what is pushed. No remote name selects a fix.

Real commits and real pushes. Each printed command runs as printed, and a ref listing before and
after shows what moved.
"""

from __future__ import annotations

import subprocess

import pytest
from conftest import git
from test_guard_push import (
    AI,
    TRAILER,
    file_commit,
    guard_on,
    printed,
    remote_head,
    run,
    run_printed,
    tree_commit,
)

from cairnkit import githook
from cairnkit.cli import main


def refs(repo) -> dict[str, str]:
    lines = git(repo, "for-each-ref", "--format=%(refname) %(objectname)").splitlines()
    return dict(line.split() for line in lines)


def head_state(repo) -> str:
    symbolic = run(repo, "symbolic-ref", "-q", "HEAD").stdout.strip()
    return symbolic or git(repo, "rev-parse", "HEAD").strip()


def moved(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}


@pytest.fixture
def remote(tmp_path):
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    return tmp_path / "remote.git"


@pytest.fixture
def forked(repo, mem, capsys, remote):
    """Pushed main with one more commit, and a local feat that forks before it and holds X."""
    guard_on(capsys)
    git(repo, "remote", "add", "origin", str(remote))
    base = git(repo, "rev-parse", "HEAD").strip()
    file_commit(repo, "M1, pushed")
    assert run(repo, "push", "-q", "origin", "main").returncode == 0
    git(repo, "tag", "v0")
    git(repo, "switch", "-qc", "feat", base)
    file_commit(repo, "F1, clean")
    tree_commit(repo, "X, with a line\n\nCo-authored-by: Claude <noreply@anthropic.com>")
    file_commit(repo, "F2, clean")
    git(repo, "switch", "-q", "main")
    return repo


def clean(repo, ref):
    return "Co-authored-by" not in git(repo, "log", "--format=%B", ref)


def start_on_main(repo, tmp_path):
    return repo


def start_on_the_branch(repo, tmp_path):
    git(repo, "switch", "-q", "feat")
    return repo


def start_at_a_tag(repo, tmp_path):
    git(repo, "switch", "-q", "--detach", "v0")
    return repo


def start_on_a_detached_head(repo, tmp_path):
    git(repo, "switch", "-q", "--detach", "main")
    return repo


def start_with_the_branch_in_another_worktree(repo, tmp_path):
    git(repo, "worktree", "add", "-q", str(tmp_path / "other"), "feat")
    return repo


def start_in_a_worktree_on_another_branch(repo, tmp_path):
    git(repo, "worktree", "add", "-q", "-b", "side", str(tmp_path / "other"), "main")
    return tmp_path / "other"


STARTS = (
    start_on_main,
    start_on_the_branch,
    start_at_a_tag,
    start_on_a_detached_head,
    start_with_the_branch_in_another_worktree,
    start_in_a_worktree_on_another_branch,
)


@pytest.mark.parametrize("start", STARTS, ids=lambda s: s.__name__.removeprefix("start_"))
def test_the_printed_fix_moves_only_the_pushed_branch(forked, tmp_path, remote, start):
    here = start(forked, tmp_path)
    before, head = refs(forked), head_state(here)

    refused = run(here, "push", "origin", "feat")
    assert refused.returncode != 0
    assert refs(forked) == before
    assert "--no-verify" not in refused.stderr
    done = run_printed(here, printed(refused.stderr, "git "))
    assert done.returncode == 0, done.stderr + refused.stderr

    after = refs(forked)
    assert moved(before, after) == {"refs/heads/feat"}, refused.stderr
    assert head_state(here) == head
    assert clean(forked, "refs/heads/feat")
    assert run(here, "status", "--porcelain").stdout == ""

    pushed = run(here, "push", "origin", "feat")
    assert pushed.returncode == 0, pushed.stderr
    assert remote_head(remote, "refs/heads/feat") == after["refs/heads/feat"]
    assert remote_head(remote) == before["refs/heads/main"]


def test_the_command_names_the_branch(forked):
    refused = run(forked, "push", "origin", "feat")
    command = printed(refused.stderr, "git rebase")
    assert command.endswith(" feat && git switch main")


def test_a_branch_in_another_worktree_runs_there(forked, tmp_path):
    other = tmp_path / "other"
    git(forked, "worktree", "add", "-q", str(other), "feat")
    refused = run(forked, "push", "origin", "feat")
    assert printed(refused.stderr, "git -C").startswith(f"git -C {other.resolve()} rebase ")


def test_a_dirty_tree_stops_the_fix_and_moves_nothing(forked):
    (forked / "f.txt").write_text("dirty\n")
    before = refs(forked)
    refused = run(forked, "push", "origin", "feat")
    done = run_printed(forked, printed(refused.stderr, "git rebase"))
    assert done.returncode != 0
    assert refs(forked) == before
    assert head_state(forked) == "refs/heads/main"


def test_two_pushed_branches_get_one_fix_each(forked, remote):
    git(forked, "switch", "-qc", "second", "main")
    tree_commit(forked, TRAILER)
    git(forked, "switch", "-q", "main")
    before = refs(forked)
    refused = run(forked, "push", "origin", "feat", "second")
    lines = [line.strip() for line in refused.stderr.splitlines() if "git rebase" in line]
    assert len(lines) == 2
    for line in lines:
        done = run_printed(forked, line)
        assert done.returncode == 0, done.stderr
    assert moved(before, refs(forked)) == {"refs/heads/feat", "refs/heads/second"}
    assert run(forked, "push", "origin", "feat", "second").returncode == 0


def test_a_root_commit_on_another_branch(repo, mem, capsys, remote):
    guard_on(capsys)
    git(repo, "checkout", "-q", "--orphan", "fresh")
    tree = git(repo, "write-tree").strip()
    message = ["commit-tree", tree, "-m", TRAILER]
    root = run(repo, *message).stdout.strip()
    git(repo, "update-ref", "refs/heads/fresh", root)
    git(repo, "switch", "-qf", "main")
    before = refs(repo)
    refused = run(repo, "push", str(remote), "fresh")
    command = printed(refused.stderr, "git rebase")
    assert "--root fresh" in command
    done = run_printed(repo, command)
    assert done.returncode == 0, done.stderr
    assert moved(before, refs(repo)) == {"refs/heads/fresh"}
    assert run(repo, "push", str(remote), "fresh").returncode == 0


def test_an_odd_branch_name_is_quoted_and_runs_as_printed(forked, remote):
    odd = "feat'$(touch${IFS}pwned)"
    git(forked, "branch", "-m", "feat", odd)
    before = refs(forked)
    refused = run(forked, "push", "origin", odd)
    done = run_printed(forked, printed(refused.stderr, "git rebase"))
    assert done.returncode == 0, done.stderr
    assert moved(before, refs(forked)) == {f"refs/heads/{odd}"}
    assert not (forked / "pwned").exists()
    assert run(forked, "push", "origin", odd).returncode == 0


@pytest.mark.parametrize("annotated", [False, True], ids=["plain", "annotated"])
def test_a_pushed_tag_is_fixed_and_moved_and_nothing_else(forked, remote, annotated):
    if annotated:
        git(forked, "tag", "-a", "v1", "-m", "Release one", "feat")
    else:
        git(forked, "tag", "v1", "feat")
    before = refs(forked)
    refused = run(forked, "push", "origin", "v1")
    assert refused.returncode != 0
    done = run_printed(forked, printed(refused.stderr, "git switch --detach"))
    assert done.returncode == 0, done.stderr + refused.stderr
    assert moved(before, refs(forked)) == {"refs/tags/v1"}
    assert head_state(forked) == "refs/heads/main"
    assert clean(forked, "refs/tags/v1")
    kind = git(forked, "cat-file", "-t", "refs/tags/v1").strip()
    assert kind == ("tag" if annotated else "commit")
    if annotated:
        assert "Release one" in git(forked, "tag", "-l", "--format=%(contents)", "v1")
    assert run(forked, "push", "origin", "v1").returncode == 0


def test_a_detached_head_pushed_by_name_moves_no_ref(forked, remote):
    git(forked, "switch", "-q", "--detach", "feat")
    before = refs(forked)
    refused = run(forked, "push", "origin", "HEAD:refs/heads/from-head")
    command = printed(refused.stderr, "git rebase")
    done = run_printed(forked, command)
    assert done.returncode == 0, done.stderr
    assert refs(forked) == before
    assert clean(forked, "HEAD")
    assert run(forked, "push", "origin", "HEAD:refs/heads/from-head").returncode == 0


def test_head_on_a_branch_pushed_by_name_acts_on_that_branch(forked, remote):
    git(forked, "switch", "-q", "feat")
    before = refs(forked)
    refused = run(forked, "push", "origin", "HEAD:refs/heads/feat")
    assert printed(refused.stderr, "git rebase").endswith(" feat")
    done = run_printed(forked, printed(refused.stderr, "git rebase"))
    assert done.returncode == 0, done.stderr
    assert moved(before, refs(forked)) == {"refs/heads/feat"}
    assert run(forked, "push", "origin", "HEAD:refs/heads/feat").returncode == 0


def test_a_commit_pushed_by_its_hash_moves_no_local_ref(forked, remote):
    tip = refs(forked)["refs/heads/feat"]
    before = refs(forked)
    refused = run(forked, "push", "origin", f"{tip}:refs/heads/by-hash")
    assert refused.returncode != 0
    done = run_printed(forked, printed(refused.stderr, "git switch --detach"))
    assert done.returncode == 0, done.stderr + refused.stderr
    assert moved(before, refs(forked)) == {"refs/remotes/origin/by-hash"}
    assert head_state(forked) == "refs/heads/main"
    held = remote_head(remote, "refs/heads/by-hash")
    assert held and "Co-authored-by" not in git(remote, "log", "--format=%B", held)


def test_a_commit_that_a_remote_holds_stays_as_it_is(pushed_ai_commit):
    repo, held = pushed_ai_commit
    refused = run(repo, "push", "origin", "feat")
    assert refused.returncode != 0
    done = run_printed(repo, printed(refused.stderr, "git rebase"))
    assert done.returncode == 0, done.stderr
    assert git(repo, "merge-base", "--is-ancestor", held, "refs/heads/feat") == ""
    assert run(repo, "push", "origin", "feat").returncode == 0


@pytest.fixture
def pushed_ai_commit(repo, mem, capsys, remote, tmp_path):
    """feat holds X, and after X a merge of main, which holds an AI line that a remote has."""
    guard_on(capsys)
    git(repo, "remote", "add", "origin", str(remote))
    assert run(repo, "push", "-q", "origin", "main").returncode == 0
    git(repo, "switch", "-qc", "feat")
    tree_commit(repo, TRAILER)
    git(repo, "switch", "-q", "main")
    held = tree_commit(repo, "held by a remote\n\nCo-authored-by: Claude <noreply@anthropic.com>")
    hook = repo / ".git" / "hooks" / "pre-push"
    saved = hook.read_text()
    hook.unlink()
    assert run(repo, "push", "-q", "origin", "main").returncode == 0
    hook.write_text(saved)
    hook.chmod(0o755)
    git(repo, "switch", "-q", "feat")
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "main")
    git(repo, "switch", "-q", "main")
    return repo, held


def test_the_printed_quick_fix_needs_no_editor(repo, mem, capsys, remote):
    guard_on(capsys)
    git(repo, "remote", "add", "origin", str(remote))
    assert run(repo, "push", "-q", "origin", "main").returncode == 0
    tree_commit(repo, TRAILER, author=AI)
    refused = run(repo, "push", "origin", "main")
    done = run_printed(repo, printed(refused.stderr, "sh "), "false")
    assert done.returncode == 0, done.stderr
    assert clean(repo, "HEAD")
    assert git(repo, "log", "-1", "--format=%an").strip() == "Test"
    assert run(repo, "push", "origin", "main").returncode == 0


def test_the_quick_fix_is_not_printed_for_a_branch_this_checkout_is_not_on(forked):
    refused = run(forked, "push", "origin", "feat")
    assert not [line for line in refused.stderr.splitlines() if line.strip().startswith("sh ")]


def test_the_quick_fix_is_not_printed_when_it_would_not_be_enough(forked):
    git(forked, "switch", "-q", "feat")
    tree_commit(forked, TRAILER)
    refused = run(forked, "push", "origin", "feat")
    assert not [line for line in refused.stderr.splitlines() if line.strip().startswith("sh ")]


# --- a remote's name cannot select a fix ---


ODD_NAMES = (
    "cairnkit-fix-commit",
    "fix-commit",
    "pre-push",
    "a'b",
    "a;b",
    "$(touch${IFS}pwned)",
    "`touch${IFS}pwned`",
    "x&&touch",
    '"quoted"',
)


@pytest.mark.parametrize("name", ODD_NAMES)
def test_no_remote_name_skips_the_check_or_changes_head(repo, mem, capsys, remote, name):
    guard_on(capsys)
    bad = tree_commit(repo, author=AI)
    added = run(repo, "remote", "add", name, str(remote))
    if added.returncode != 0:
        pytest.skip(f"git refuses the remote name {name}")
    result = run(repo, "push", name, "main")
    assert result.returncode != 0
    assert bad[:7] in result.stderr
    assert remote_head(remote) == ""
    assert git(repo, "rev-parse", "HEAD").strip() == bad
    assert not (repo / "pwned").exists()


def test_a_push_to_a_folder_named_like_the_fix_is_checked(repo, mem, capsys, tmp_path):
    guard_on(capsys)
    git(tmp_path, "init", "-q", "--bare", "cairnkit-fix-commit")
    bad = tree_commit(repo, author=AI)
    result = run(repo, "push", "../cairnkit-fix-commit", "main")
    assert result.returncode != 0
    assert git(repo, "rev-parse", "HEAD").strip() == bad


def test_the_hook_file_has_no_fix_mode(repo, mem, capsys):
    guard_on(capsys)
    bad = tree_commit(repo, TRAILER)
    hook = repo / ".git" / "hooks" / "pre-push"
    result = subprocess.run(
        ["sh", str(hook), "cairnkit-fix-commit", "any"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        input="",
    )
    assert result.returncode == 0
    assert git(repo, "rev-parse", "HEAD").strip() == bad


def test_the_fix_file_is_gone_with_the_guard(repo, mem, capsys):
    guard_on(capsys)
    path = repo / ".git" / githook.FIX_FILE
    assert path.is_file()
    assert not git(repo, "status", "--porcelain")
    assert main(["hooks", "uninstall"]) == 0
    assert not path.exists()


def test_a_lost_fix_file_is_named_and_an_install_brings_it_back(repo, mem, capsys, remote):
    guard_on(capsys)
    tree_commit(repo, author=AI)
    (repo / ".git" / githook.FIX_FILE).unlink()
    refused = run(repo, "push", str(remote), "main")
    assert refused.returncode != 0
    assert "`memory hooks install`" in refused.stderr
    assert "git rebase" not in refused.stderr
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    refused = run(repo, "push", str(remote), "main")
    assert run_printed(repo, printed(refused.stderr, "git rebase")).returncode == 0
    assert run(repo, "push", str(remote), "main").returncode == 0


# --- a lost base is not an install ---


def test_a_deleted_base_refuses_with_a_fix_that_works(repo, mem, capsys, remote):
    guard_on(capsys)
    bad = tree_commit(repo, author=AI)
    (repo / ".git" / githook.BASE_FILE).unlink()
    refused = run(repo, "push", str(remote), "main")
    assert refused.returncode != 0
    assert bad[:7] in refused.stderr
    assert githook.BASE_FILE in refused.stderr
    assert "older commit" not in refused.stderr
    assert remote_head(remote) == ""
    assert not (repo / ".git" / githook.BASE_FILE).exists()
    done = run_printed(repo, printed(refused.stderr, "git rebase"))
    assert done.returncode == 0, done.stderr
    assert run(repo, "push", str(remote), "main").returncode == 0


def test_a_commit_from_before_the_guard_is_checked_when_the_base_is_deleted(repo, mem, capsys, remote):
    tree_commit(repo, author=AI)
    guard_on(capsys)
    (repo / ".git" / githook.BASE_FILE).unlink()
    assert run(repo, "push", str(remote), "main").returncode != 0


def test_an_install_does_not_turn_a_deleted_base_into_a_new_one(repo, mem, capsys, remote):
    guard_on(capsys)
    bad = tree_commit(repo, author=AI)
    (repo / ".git" / githook.BASE_FILE).unlink()
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    assert not (repo / ".git" / githook.BASE_FILE).exists()
    refused = run(repo, "push", str(remote), "main")
    assert refused.returncode != 0 and bad[:7] in refused.stderr


def test_a_refresh_does_not_turn_a_deleted_base_into_a_new_one(repo, mem, capsys, remote):
    guard_on(capsys)
    tree_commit(repo, author=AI)
    (repo / ".git" / githook.BASE_FILE).unlink()
    assert main(["init", "--refresh"]) == 0
    assert run(repo, "push", str(remote), "main").returncode != 0


def test_an_install_writes_the_base_so_a_first_push_is_no_trap(repo, mem, capsys, remote):
    tree_commit(repo, author=AI)
    guard_on(capsys)
    assert (repo / ".git" / githook.BASE_FILE).is_file()
    result = run(repo, "push", str(remote), "main")
    assert result.returncode == 0, result.stderr
    assert "1 older commit(s)" in result.stderr


def test_a_reinstall_sets_a_new_base_and_a_later_commit_is_new(repo, mem, capsys, remote):
    guard_on(capsys)
    tree_commit(repo, author=AI)
    assert main(["hooks", "uninstall"]) == 0
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    result = run(repo, "push", str(remote), "main")
    assert result.returncode == 0, result.stderr
    assert "1 older commit(s)" in result.stderr
    tree_commit(repo, author=AI)
    assert run(repo, "push", str(remote), "main").returncode != 0
