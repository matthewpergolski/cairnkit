"""Defects that real agents reported against 0.3.1. Each one broke the goal in the README."""

from __future__ import annotations

import pytest
from conftest import git

from cairnkit.cli import main
from cairnkit.hookrun import pre_commit
from cairnkit.memory import Memory
from cairnkit.paths import find_project, merged_checker
from cairnkit.secretscan import find_secrets


def _commit(repo, name):
    (repo / name).write_text("x\n")
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)


def test_a_branch_with_only_a_remote_copy_is_not_merged(repo):
    _commit(repo, "a")
    git(repo, "checkout", "-qb", "work")
    _commit(repo, "b")
    git(repo, "update-ref", "refs/remotes/origin/work", "HEAD")
    git(repo, "checkout", "-q", "-")
    git(repo, "branch", "-qD", "work")
    assert merged_checker(repo)("work") is False


def test_a_branch_in_no_ref_reads_as_ended(repo):
    _commit(repo, "a")
    assert merged_checker(repo)("gone") is True


def test_a_squash_merged_branch_with_a_local_copy_reads_as_merged(repo):
    _commit(repo, "a")
    base = git(repo, "branch", "--show-current").strip()
    git(repo, "checkout", "-qb", "work")
    _commit(repo, "b")
    _commit(repo, "c")
    git(repo, "checkout", "-q", base)
    git(repo, "merge", "-q", "--squash", "work")
    git(repo, "commit", "-qm", "squash")
    assert merged_checker(repo)("work") is True


def test_an_open_branch_is_not_merged(repo):
    _commit(repo, "a")
    base = git(repo, "branch", "--show-current").strip()
    git(repo, "checkout", "-qb", "work")
    _commit(repo, "b")
    git(repo, "checkout", "-q", base)
    assert merged_checker(repo)("work") is False


def test_a_memory_problem_does_not_stop_a_commit(mem, repo):
    facts = mem / "facts" / "main.jsonl"
    facts.parent.mkdir(exist_ok=True)
    with facts.open("a") as fh:
        fh.write("not json\n")
    assert pre_commit(find_project(), None) == 0


def test_a_commit_of_the_memory_link_is_still_refused(mem, repo, capsys):
    git(repo, "add", "-f", "memory-bank")
    assert pre_commit(find_project(), None) == 1
    assert "private memory" in capsys.readouterr().err


def test_a_held_by_file_on_another_branch_is_not_a_problem(mem, repo, capsys):
    _commit(repo, "a")
    base = git(repo, "branch", "--show-current").strip()
    git(repo, "checkout", "-qb", "work")
    _commit(repo, "rules.md")
    assert main(["add", "A rule.", "--area", "x", "--basis", "told", "--source", "session:1"]) == 0
    fact = capsys.readouterr().out.strip().split()[-1]
    assert (
        main(["change", fact, "--status", "promoted", "--held-by", "rules.md", "--reason", "moved"])
        == 0
    )
    git(repo, "checkout", "-q", base)
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0


@pytest.mark.parametrize(
    "text",
    [
        "INVITE_CODE=abc123def",
        "export HOST_CODE=9f8e7d6c",
        "CRON_SECRET=hunter2hunter2",
        "MY_API_KEY: abcdef123456",
        "STRIPE_KEY=rk_live_abcdefghijklmnop",
        "rk_live_abcdefghijklmnop1234",
        "sk_test_abcdefghijklmnop1234",
        "Authorization: Bearer abcdefghijklmnop123456",
        "open https://example.com/join?k=abcd1234ef",
        "https://example.com/x?a=1&token=abcd1234ef",
    ],
)
def test_common_secret_shapes_are_found(text):
    assert find_secrets(text)


@pytest.mark.parametrize(
    "text",
    [
        "EXIT_CODE=failed in the deploy step",
        "STATUS_CODE=500000 is not a real code",
        "Set CRON_SECRET=$CRON_SECRET in the shell",
        "Use API_KEY=<your-key> from the vault",
        "PUBLIC_KEY=abcdef123456 is safe to print",
        "the bearer token expired on Tuesday afternoon",
        "see https://example.com/page?page=200000",
    ],
)
def test_ordinary_text_is_not_a_secret(text):
    assert not find_secrets(text)


def test_check_warns_about_a_secret_in_notes(mem, capsys):
    notes = mem / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "status.md").write_text("Token: CRON_SECRET=hunter2hunter2\n")
    assert main(["check"]) == 0
    assert "status.md" in capsys.readouterr().out


def test_search_takes_several_words_with_no_quotes(mem, capsys):
    add = ["--area", "x", "--basis", "seen", "--source", "session:1"]
    assert main(["add", "The deploy needs a full pool.", *add]) == 0
    capsys.readouterr()
    assert main(["search", "deploy", "pool"]) == 0
    assert "full pool" in capsys.readouterr().out


def test_a_rule_with_a_summary_is_written(mem, capsys):
    add = ["--area", "x", "--basis", "told", "--source", "session:1", "--kind", "rule"]
    assert main(["add", "Never force push.", "--summary", "No force.", *add]) == 0
    captured = capsys.readouterr()
    assert "summary" in captured.out + captured.err
    states = Memory.open(find_project(), None).states.values()
    assert [s.get("summary") for s in states if s["text"] == "Never force push."] == [None]


def test_add_works_with_no_area(mem, capsys):
    assert main(["add", "A fact.", "--basis", "seen", "--source", "session:1"]) == 0
    states = Memory.open(find_project(), None).states.values()
    assert [s["area"] for s in states if s["text"] == "A fact."] == ["general"]


def test_until_merged_with_an_unknown_branch_says_so(mem, repo, capsys):
    add = ["--area", "x", "--basis", "seen", "--source", "session:1"]
    assert main(["add", "Note.", "--until-merged", "not-yet", *add]) == 0
    assert "not-yet" in capsys.readouterr().out
