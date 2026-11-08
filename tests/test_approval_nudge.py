"""`memory add` says when a rule reads as the owner's yes to one piece of work."""

from __future__ import annotations

import pytest
from test_told_claims import agent_add, facts, prompt, transcripts  # noqa: F401

from cairnkit.cli import main
from cairnkit.landed import one_work

NUDGE = "reads as approval of one piece of work"

APPROVALS = [
    "Yes to migration 0018.",
    "The owner approved the Home Screen test.",
    "Go ahead with the PR #158 merge; fix the finding later.",
    "Ship the banner change for this release only.",
    "Owner OK'd the new parser.",
    "Owner OK\u2019d the new parser.",
    "LGTM on the auth refactor.",
    "Owner approves the schema change.",
    "green light for the Postgres move",
    "Signed off on the cache rewrite.",
]
POLICIES = [
    "Never force-push to main.",
    "Every PR needs one review before merge.",
    "Ask the owner to approve each deploy.",
    "Use approved licenses only",
    "Only merge PRs that are approved by the owner",
    "Never edit migration 0001; it is the baseline",
    "Keep issue refs as #123 in commit subjects",
    "Do not go ahead with a deploy on Fridays",
]


def add(capsys, *args: str) -> str:
    capsys.readouterr()
    assert main(["add", *args]) == 0
    return capsys.readouterr().out


@pytest.mark.parametrize("text", APPROVALS)
def test_an_approval_of_one_piece_of_work_reads_as_one(text):
    assert one_work(text)


@pytest.mark.parametrize("text", POLICIES)
def test_a_lasting_or_negated_policy_is_no_approval(text):
    assert not one_work(text)


@pytest.mark.parametrize("text", APPROVALS[:4])
@pytest.mark.parametrize("basis", ["told", "seen"])
def test_a_rule_that_approves_one_piece_of_work_gets_the_note(mem, capsys, text, basis):
    out = add(capsys, text, "--kind", "rule", "--basis", basis)
    note = next(line for line in out.splitlines() if NUDGE in line)
    assert "--kind decision" in note and "--files" in note and "--until-merged" in note
    assert f"--basis {basis}" in note


def test_the_note_for_a_told_rule_says_when_it_binds(mem, capsys):
    out = add(capsys, "Yes to migration 0018.", "--kind", "rule", "--basis", "told")
    note = next(line for line in out.splitlines() if NUDGE in line)
    assert "owner's words in this turn" in note and "ask the owner" in note


@pytest.mark.parametrize("text", POLICIES)
def test_a_lasting_policy_gets_no_note(mem, capsys, text):
    assert NUDGE not in add(capsys, text, "--kind", "rule", "--basis", "told")


def test_a_decision_gets_no_note(mem, capsys):
    out = add(capsys, "Yes to migration 0018.", "--kind", "decision", "--files", "README.md")
    assert NUDGE not in out


def test_the_printed_command_replaces_a_told_rule_in_the_turn_of_the_owner(
    mem, capsys, monkeypatch
):
    prompt(capsys, monkeypatch, "Yes to migration 0018.")
    out = agent_add(capsys, monkeypatch, "Yes to migration 0018.")
    rule = facts(mem)[-1]["id"]
    assert "told: confirmed" in out and NUDGE in out
    out = agent_add(
        capsys,
        monkeypatch,
        "Yes to migration 0018.",
        "--kind",
        "decision",
        "--supersedes",
        rule,
        "--files",
        "README.md",
    )
    assert "told: confirmed" in out and "not superseded" not in out
    ended = [r for r in facts(mem) if r.get("id") == rule and r.get("status") == "superseded"]
    assert ended, "the decision replaced the told rule"
