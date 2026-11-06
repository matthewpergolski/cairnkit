"""Defects that an independent review found in the export and import fixes and the rule hint."""

from __future__ import annotations

import pytest
from test_add_defaults import _add
from test_transfer import added, new_repo, ok

from cairnkit.cli import main
from cairnkit.secretscan import find_secrets, mask

TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.mark.parametrize("mark", ["\u202a", "\u200b", "\u2066", "\ufeff"])
def test_a_mark_that_shows_as_nothing_inside_a_token_hides_no_secret(mark):
    text = f"token {TOKEN[:16]}{mark}{TOKEN[16:]} for ci"
    assert find_secrets(text) == ["GitHub token"]
    assert TOKEN[16:] not in mask(text)


def test_memory_add_refuses_a_token_split_by_a_bidi_mark(mem, capsys):
    capsys.readouterr()
    assert main(["add", f"token {TOKEN[:16]}\u202a{TOKEN[16:]} for ci"]) != 0


def plan_of(tmp_path, text: str, name: str = "proj") -> tuple[str, str]:
    root = new_repo(tmp_path / name)
    plan = ok(root, "import", "-", stdin=text)
    return plan.split("Would skip", 1)[0], plan


def test_a_plain_line_under_a_heading_is_an_entry_not_a_heading(tmp_path):
    adds, _ = plan_of(
        tmp_path,
        "## Instructions\nNever commit to main\n[2026-01-01] - Use ruff\n"
        "Always run tests first\n[2026-01-02] - Keep functions small\n",
    )
    for text in ("Never commit to main", "Use ruff", "Always run tests first", "Keep functions"):
        assert text in adds


def test_prose_around_the_code_block_is_not_read(tmp_path):
    adds, plan = plan_of(
        tmp_path,
        "Sure! Here's everything about you and the project\n```\n"
        "[2026-03-01] - Never commit directly to main\n[2026-02-01] - Chose SQLite over Postgres\n"
        "```\nLet me know if you want more\n",
    )
    assert "Never commit directly to main" in adds and "Chose SQLite" in adds
    assert "personal" not in plan and "Let me know" not in plan


def test_other_projects_go_through_the_project_filter(tmp_path):
    adds, _ = plan_of(tmp_path, "## Other projects\n- Billing service uses Stripe\n")
    assert "Stripe" not in adds


@pytest.mark.parametrize("heading", ["Health checks", "Job queue decisions", "Life of a request"])
def test_project_words_are_not_personal(tmp_path, heading):
    _, plan = plan_of(tmp_path, f"## {heading}\n- The probe runs each minute.\n")
    assert "personal" not in plan


def test_rules_for_me_are_rules(tmp_path):
    adds, _ = plan_of(tmp_path, "## Rules for me\n- Always run the tests.\n")
    assert "rule, loads as data" in adds


@pytest.mark.parametrize(
    ("text", "hint"),
    [("Always-on cache is enabled in staging.", False), ("Don\u2019t use tabs.", True)],
)
def test_the_rule_hint_needs_a_whole_word(mem, capsys, text, hint):
    _, out = _add(capsys, text, "--basis", "seen")
    assert ("reads as a rule" in out) is hint


def test_an_import_writes_the_plain_lines_it_planned(tmp_path):
    root = new_repo(tmp_path / "proj")
    ok(root, "import", "-", "--yes", stdin="## Decisions\nChose SQLite over Postgres\n")
    assert [f["text"] for f in added(tmp_path / "proj.memory")] == ["Chose SQLite over Postgres"]
