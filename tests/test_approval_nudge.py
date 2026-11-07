"""`memory add` says when a rule reads as the owner's yes to one piece of work."""

from __future__ import annotations

import pytest

from cairnkit.cli import main

NUDGE = "reads as approval of one piece of work"


def add(capsys, *args: str) -> str:
    capsys.readouterr()
    assert main(["add", *args]) == 0
    return capsys.readouterr().out


@pytest.mark.parametrize(
    "text",
    [
        "Yes to migration 0018.",
        "The owner approved the Home Screen test.",
        "Go ahead with the PR #158 merge; fix the finding later.",
        "Ship the banner change for this release only.",
    ],
)
@pytest.mark.parametrize("basis", ["told", "seen"])
def test_a_rule_that_approves_one_piece_of_work_gets_the_note(mem, capsys, text, basis):
    out = add(capsys, text, "--kind", "rule", "--basis", basis)
    note = next(line for line in out.splitlines() if NUDGE in line)
    assert "--kind decision" in note and "--files" in note and "--until-merged" in note


@pytest.mark.parametrize(
    "text",
    [
        "Never force-push to main.",
        "Every PR needs one review before merge.",
        "Ask the owner to approve each deploy.",
    ],
)
def test_a_lasting_policy_gets_no_note(mem, capsys, text):
    assert NUDGE not in add(capsys, text, "--kind", "rule", "--basis", "told")


def test_a_decision_gets_no_note(mem, capsys):
    out = add(capsys, "Yes to migration 0018.", "--kind", "decision", "--files", "README.md")
    assert NUDGE not in out
