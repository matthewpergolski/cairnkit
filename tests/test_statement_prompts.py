"""The owner states what only the conversation holds. A false fire costs the owner a turn."""

from __future__ import annotations

import pytest
from conftest import FIXTURES, read_jsonl

from cairnkit.signals import is_correction, is_statement

ROWS = read_jsonl(FIXTURES / "statement_prompts.jsonl")
# The held split was written before the detector, and was read once, after the tuning.
LIMITS = {"tune": (0, 0), "held": (2, 1)}


@pytest.mark.parametrize("split", LIMITS)
def test_the_labelled_set_stays_at_its_measured_count(split):
    rows = [row for row in ROWS if row["split"] == split]
    false_fires = [r["prompt"] for r in rows if is_statement(r["prompt"]) and not r["statement"]]
    misses = [r["prompt"] for r in rows if r["statement"] and not is_statement(r["prompt"])]
    most_false, most_missed = LIMITS[split]
    assert len(false_fires) <= most_false, false_fires
    assert len(misses) <= most_missed, misses


def test_of_the_prompts_that_are_no_correction_only_a_real_limit_fires():
    rows = read_jsonl(FIXTURES / "correction_prompts.jsonl")
    fired = [row["prompt"] for row in rows if not row["correction"] and is_statement(row["prompt"])]
    assert fired == ["Never log the token. Now add the logger."]


@pytest.mark.parametrize(
    "prompt",
    [
        "did we decide to keep it?",
        "if we decided to keep it, what is next?",
        'the log says "we decided to retry", what does it mean',
        "<task-notification>we decided to retry</task-notification>",
        "Before you finish, run `memory add` for what we decided",
    ],
)
def test_a_question_a_condition_a_quote_or_a_tool_turn_states_nothing(prompt):
    assert not is_statement(prompt)


def test_a_statement_after_a_request_counts_and_a_long_paste_does_not():
    assert is_statement("Set the window to 45. The reason for this work: the gateway restarts.")
    assert not is_statement("Summarize this log:\n" + "line\n" * 200 + "we decided to retry")


def test_a_correction_is_its_own_signal():
    assert is_correction("you broke the login page")
    assert not is_statement("you broke the login page")
