"""A mask is what a load shows. Stored as text, it takes the place of the true word for good."""

from __future__ import annotations

import pytest

from cairnkit.cli import main

ADD = ["--basis", "seen", "--source", "session:2026-11-01"]
WORD = "deploy-bot"
TRUE = f"Trap: nightly job runs as {WORD} and fails on Sunday"
COPY = "Trap: nightly job runs as [secret: ADMIN_PASSWORD] and fails on Sunday"
REFUSAL = "this text came from a masked load"


def stored(mem) -> str:
    return "".join(path.read_text() for path in (mem / "facts").glob("*.jsonl"))


def add_masked(repo, capsys, text=TRUE, *extra) -> str:
    """A fact with a word that a `.env` file holds from now on."""
    assert main(["add", text, *ADD, *extra]) == 0
    fact_id = capsys.readouterr().out.strip().split()[-1]
    (repo / ".env").write_text(f"ADMIN_PASSWORD={WORD}\n")
    return fact_id


def refused(capsys, *args) -> None:
    assert main(["add", *args, *ADD]) == 1
    captured = capsys.readouterr()
    assert REFUSAL in captured.err
    assert len(captured.err.strip().splitlines()) == 1
    assert "leave the fact" in captured.err


def test_a_repeat_from_a_masked_load_keeps_the_true_word(repo, mem, capsys):
    fact_id = add_masked(repo, capsys)
    before = stored(mem)
    refused(capsys, COPY)
    assert stored(mem) == before
    assert main(["load"]) == 0
    assert fact_id in capsys.readouterr().out
    assert WORD in stored(mem)


def test_a_supersede_with_a_mask_changes_nothing(repo, mem, capsys):
    fact_id = add_masked(repo, capsys)
    before = stored(mem)
    refused(capsys, COPY, "--supersedes", fact_id)
    assert stored(mem) == before


def test_an_agent_cannot_copy_a_mask_over_an_owner_rule(repo, mem, capsys, monkeypatch):
    rule = f"Always use the {WORD} account"
    fact_id = add_masked(repo, capsys, rule, "--kind", "rule")
    before = stored(mem)
    monkeypatch.setenv("CLAUDECODE", "1")
    refused(
        capsys,
        "Always use the [secret: ADMIN_PASSWORD] account",
        "--kind",
        "rule",
        "--supersedes",
        fact_id,
    )
    assert stored(mem) == before


@pytest.mark.parametrize(
    "text",
    [
        "the login is password=[secret: assigned secret] for staging",
        "[secret: hidden text]",
        "the value is [secret: env value] here",
        "the job runs as [secret: ADMIN_PASS",
        "the job runs as [secret: ADMIN_PASS...",
        "the job runs as [secret: ADMIN_PASS…",
        "the job runs as [secret:",
        "the job runs as [secret: ADMIN_PASS... and fails",
        "...ret: ADMIN_PASSWORD] and fails on Sunday",
    ],
)
def test_each_form_of_a_mask_is_refused(mem, capsys, text):
    before = stored(mem)
    refused(capsys, text)
    assert stored(mem) == before


@pytest.mark.parametrize("field", ["--summary", "--area"])
def test_a_mask_in_a_summary_or_an_area_is_refused(mem, capsys, field):
    refused(capsys, "plain text on the staging db", field, "[secret: ADMIN_PASSWORD]")


@pytest.mark.parametrize(
    "text",
    [
        "Use the [hidden] attribute on the panel",
        "The field arr[secret: 1] is the second one",
        "The [secret] section of the template stays",
        "Read [secret: a lower case name] from the docs for this",
        "...and the list ends in [done] now",
    ],
)
def test_a_fact_with_brackets_is_fine(mem, capsys, text):
    assert main(["add", text, *ADD]) == 0
    assert text in stored(mem)


def test_a_plain_word_catch_says_leave_it_and_offers_no_rewrite(repo, mem, capsys):
    fact_id = add_masked(repo, capsys)
    capsys.readouterr()
    assert main(["load"]) == 0
    note = next(line for line in capsys.readouterr().out.splitlines() if "`.env` secret" in line)
    assert "Leave the fact" in note
    assert "--supersedes" not in note and "memory purge" not in note
    assert main(["show", fact_id]) == 0
    shown = capsys.readouterr().out
    assert "Leave the fact" in shown
    assert "--supersedes" not in shown and "memory purge" not in shown
