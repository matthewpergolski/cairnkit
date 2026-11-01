"""A load cut by git says so. A timeout never reads as "not in git" or as branch main."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import sys
import time

import pytest
from conftest import add_worktree, git, make_fact, read_jsonl, write_facts

from cairnkit import deadline, store
from cairnkit.paths import find_project

FLAGS = ["--basis", "seen", "--source", "session:2026-11-01"]
# The shortest timeout of any adapter hook. `test_time_budget` holds adapters to it.
SHORTEST_HOOK_TIMEOUT = 5


def _fake_git(tmp_path, seconds):
    folder = tmp_path / "fake-bin"
    folder.mkdir(exist_ok=True)
    fake = folder / "git"
    fake.write_text(f'#!/bin/sh\nsleep {seconds}\nexec "{shutil.which("git")}" "$@"\n')
    fake.chmod(0o755)
    return {**os.environ, "PATH": f"{folder}{os.pathsep}{os.environ['PATH']}"}


def _command(cwd, env, *args):
    begun = time.monotonic()
    done = subprocess.run(
        [sys.executable, "-m", "cairnkit", *args],
        cwd=cwd,
        env=env,
        input="{}",
        capture_output=True,
        text=True,
        timeout=60,
    )
    return done, time.monotonic() - begun


def _on_feat(repo, mem):
    """Branch feat, with 2 short notes, one long fact and a branch note."""
    git(repo, "switch", "-qc", "feat")
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Note one on feat.", scope="short",
                      until_branch_merged="feat", writer="feat"),
            make_fact("f-20261001-0002", "Note two on feat.", scope="short",
                      until_branch_merged="feat", writer="feat"),
            make_fact("f-20261001-0003", "A long fact."),
        ],
        name="feat.jsonl",
    )  # fmt: skip
    (mem / "branches").mkdir(exist_ok=True)
    (mem / "branches" / "feat.md").write_text("The branch note text.\n")


@pytest.mark.parametrize(
    "args", [["load"], ["hook", "session-start", "--agent", "claude"]], ids=["load", "session"]
)
def test_a_hung_git_keeps_the_notes_of_the_known_branch_and_says_it_was_cut(
    mem, repo, tmp_path, args
):
    _on_feat(repo, mem)
    done, took = _command(repo, _fake_git(tmp_path, 600), *args)
    assert done.returncode == 0
    assert took < 7.5
    for text in ("Note one on feat.", "Note two on feat.", "The branch note text.", "A long fact."):
        assert text in done.stdout
    assert "## Short-term (branch feat)" in done.stdout
    assert "(branch main)" not in done.stdout
    cut = [line for line in done.stdout.splitlines() if "git did not answer" in line]
    assert len(cut) == 1
    assert "0 fact(s) held back" in cut[0]


def test_a_healthy_load_says_nothing_of_git(mem, repo):
    _on_feat(repo, mem)
    done, _ = _command(repo, os.environ, "load")
    assert "git did not answer" not in done.stdout


def test_a_load_that_cannot_name_the_branch_counts_what_it_held_back(mem, repo, tmp_path):
    _on_feat(repo, mem)
    (repo / ".git" / "HEAD").write_text("not a ref\n")
    done, _ = _command(repo, _fake_git(tmp_path, 600), "load")
    assert done.returncode == 0
    assert "Note one on feat." not in done.stdout
    cut = next(line for line in done.stdout.splitlines() if "git did not answer" in line)
    assert "the branch" in cut
    assert "2 fact(s) held back" in cut
    assert "2 active fact(s) not shown" in done.stdout
    assert "(branch main)" not in done.stdout


def test_a_failed_git_binary_is_a_cut_too(mem, repo, tmp_path):
    _on_feat(repo, mem)
    folder = tmp_path / "broken-bin"
    folder.mkdir()
    fake = folder / "git"
    fake.write_text("#!/nonexistent/interpreter\n")
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{folder}{os.pathsep}{os.environ['PATH']}"}
    done, _ = _command(repo, env, "load")
    assert "Note one on feat." in done.stdout
    assert "git did not answer" in done.stdout


def test_add_short_under_a_hung_git_lands_on_the_known_branch(mem, repo, tmp_path):
    _on_feat(repo, mem)
    text = "A note while git hangs."
    done, took = _command(repo, _fake_git(tmp_path, 600), "add", text, "--short", *FLAGS)
    assert done.returncode == 0, done.stderr
    assert took < SHORTEST_HOOK_TIMEOUT
    assert "not in git" not in done.stdout
    assert "git did not answer" in done.stdout
    assert "no default branch" not in done.stdout
    record = next(r for r in read_jsonl(mem / "facts" / "feat.jsonl") if r.get("text") == text)
    assert record["until_branch_merged"] == "feat"
    assert record["writer"] == "feat"
    assert text not in (mem / "facts" / "main.jsonl").read_text()
    shown, _ = _command(repo, os.environ, "load")
    assert text in shown.stdout


def test_add_short_with_an_unreadable_branch_says_so_and_stays_visible(mem, repo, tmp_path):
    _on_feat(repo, mem)
    head = repo / ".git" / "HEAD"
    good = head.read_text()
    head.write_text("not a ref\n")
    text = "A note with no branch to name."
    done, took = _command(repo, _fake_git(tmp_path, 600), "add", text, "--short", *FLAGS)
    assert done.returncode == 0, done.stderr
    assert took < SHORTEST_HOOK_TIMEOUT
    assert "not in git" not in done.stdout
    assert "branch-unread" in done.stdout
    assert text not in (mem / "facts" / "main.jsonl").read_text()
    assert text in (mem / "facts" / "branch-unread.jsonl").read_text()
    head.write_text(good)
    shown, _ = _command(repo, os.environ, "load")
    assert text in shown.stdout


def test_add_in_a_worktree_under_a_hung_git_uses_its_branch(mem, repo, tmp_path):
    tree = add_worktree(repo, "side")
    assert git(tree, "branch", "--show-current").strip() == "side"
    _command(tree, os.environ, "load")
    text = "A note in the worktree while git hangs."
    done, took = _command(tree, _fake_git(tmp_path, 600), "add", text, "--short", *FLAGS)
    assert done.returncode == 0, done.stderr
    assert took < SHORTEST_HOOK_TIMEOUT
    record = next(r for r in read_jsonl(mem / "facts" / "side.jsonl") if r.get("text") == text)
    assert record["until_branch_merged"] == "side"


def test_add_during_a_rebase_under_a_hung_git_uses_the_branch_being_rebased(mem, repo, tmp_path):
    git(repo, "switch", "-qc", "feat")
    folder = repo / ".git" / "rebase-merge"
    folder.mkdir()
    (folder / "head-name").write_text("refs/heads/feat\n")
    (repo / ".git" / "HEAD").write_text(git(repo, "rev-parse", "HEAD"))
    text = "A note while a rebase runs."
    done, _ = _command(repo, _fake_git(tmp_path, 600), "add", text, "--short", *FLAGS)
    assert done.returncode == 0, done.stderr
    record = next(r for r in read_jsonl(mem / "facts" / "feat.jsonl") if r.get("text") == text)
    assert record["until_branch_merged"] == "feat"


def test_a_plain_folder_stays_plain_under_a_hung_git(tmp_path, monkeypatch):
    folder = tmp_path / "plain"
    folder.mkdir()
    env = _fake_git(tmp_path, 600)
    done, _ = _command(folder, os.environ, "init", "--no-default-rules")
    assert done.returncode == 0, done.stderr
    done, took = _command(folder, env, "add", "A plain note.", "--short", *FLAGS)
    assert done.returncode == 0, done.stderr
    assert took < SHORTEST_HOOK_TIMEOUT
    assert "this folder is not in git" in done.stdout


def test_a_repo_with_a_hung_git_is_still_a_repo(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", _fake_git(tmp_path, 600)["PATH"])
    sub = repo / "deep" / "er"
    sub.mkdir(parents=True)
    with deadline.within(0):
        project = find_project(sub)
    assert project.is_git
    assert project.root.resolve() == repo.resolve()


def test_add_with_a_slow_git_stays_under_the_shortest_hook_timeout(mem, repo, tmp_path):
    _on_feat(repo, mem)
    text = "A fact while each git call takes a second."
    done, took = _command(repo, _fake_git(tmp_path, 1), "add", text, *FLAGS)
    assert done.returncode == 0, done.stderr
    assert took < SHORTEST_HOOK_TIMEOUT
    assert text in (mem / "facts" / "feat.jsonl").read_text()


def test_add_with_a_hung_git_and_a_held_lock_refuses_under_the_shortest_hook_timeout(
    mem, repo, tmp_path
):
    _on_feat(repo, mem)
    text = "A fact that cannot get the lock."
    with (mem / "facts" / store.WRITE_LOCK).open("ab") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        done, took = _command(repo, _fake_git(tmp_path, 600), "add", text, *FLAGS)
    assert done.returncode == 1
    assert "Nothing was written" in done.stderr
    assert took < SHORTEST_HOOK_TIMEOUT
    assert text not in (mem / "facts" / "feat.jsonl").read_text()


@pytest.mark.parametrize(
    "extra",
    [["change", "f-20261001-0003", "--reason", "looked"], ["keep", "f-20261001-0001"]],
    ids=["change", "keep"],
)
def test_other_writes_stay_under_the_shortest_hook_timeout(mem, repo, tmp_path, extra):
    _on_feat(repo, mem)
    done, took = _command(repo, _fake_git(tmp_path, 600), *extra)
    assert done.returncode == 0, done.stderr
    assert took < SHORTEST_HOOK_TIMEOUT
