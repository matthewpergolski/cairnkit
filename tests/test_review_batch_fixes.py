"""Defects that an independent review found in the export and import fixes and the rule hint."""

from __future__ import annotations

import pytest
from test_add_defaults import _add
from test_transfer import added, new_repo, ok

from cairnkit.cli import main
from cairnkit.secretscan import find_secrets, mask

TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.mark.parametrize(
    "mark", ["\u202a", "\u200b", "\u2066", "\ufeff", "\x7f", "\x01", "\x85", "\x1b[0m", "\xad"]
)
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


NOT_READ = "no list item and no dated line, so not read"


def skipped(plan: str) -> str:
    return plan.split("Would skip", 1)[1]


def test_a_plain_line_is_listed_as_not_read_and_changes_no_section(tmp_path):
    adds, plan = plan_of(
        tmp_path,
        "## Instructions\nNever commit to main\n[2026-01-01] - Use ruff\n"
        "Rules are strict\n[2026-01-02] - Keep functions small\n",
    )
    assert "Use ruff" in adds and "Keep functions small" in adds
    assert adds.count("rule, loads as data") == 2
    for text in ("Never commit to main", "Rules are strict"):
        assert text not in adds and f"{NOT_READ} (put `- ` in front to add it): {text}" in plan


def test_prose_tables_and_code_are_listed_and_never_stored(tmp_path):
    answer = (
        "Sure! Here's everything about you and the project\n## Decisions\n"
        "- Chose SQLite over Postgres\nBecause merging matters.\n"
        "That is everything I know about the project\n| Item | Value |\n|---|---|\n"
        "Run it like this:\n```bash\nuv run memory check\n```\n## Traps and lessons\n"
        "[2026-03-01] - The cache key needs the locale\nLet me know if you want more\n"
    )
    adds, plan = plan_of(tmp_path, answer)
    assert "Chose SQLite" in adds and "The cache key needs the locale" in adds
    assert "personal" not in plan
    for text in ("Sure!", "Because merging", "That is everything", "| Item", "Let me know"):
        assert text not in adds and text in skipped(plan)
    assert "uv run memory check" not in adds


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


def test_an_import_writes_no_plain_line(tmp_path):
    root = new_repo(tmp_path / "proj")
    ok(root, "import", "-", "--yes", stdin="## Decisions\nChose SQLite over Postgres\n- Use uv\n")
    assert [f["text"] for f in added(tmp_path / "proj.memory")] == ["Use uv"]


@pytest.mark.parametrize(
    "mark",
    ["\u061c", "\u180e", "\u206a", "\u3164", "\u2800", "\ufff9", "\u17b4", "\U000e0100"],
)
def test_any_mark_that_shows_as_nothing_hides_no_secret(mark):
    text = f"CI uses {TOKEN[:16]}{mark}{TOKEN[16:]} here"
    assert find_secrets(text) == ["GitHub token"]
    assert TOKEN[16:] not in mask(text)


def test_a_token_split_after_its_shape_is_masked_whole():
    key = "sk-proj-aB3dE5gH7jK9mN1pQ3sT"
    tail = "vW5yZ7bC9eF1gH3iJ5kL7mN9"
    assert tail not in mask(f"uses {key}\u200b{tail} ok")


def test_a_line_with_no_secret_keeps_its_marks():
    text = "cafe\u0301 \U0001f468\u200d\U0001f469 plain line"
    assert mask(text) == text


def test_a_list_item_that_ends_with_a_colon_is_an_entry(tmp_path):
    adds, plan = plan_of(
        tmp_path,
        "## Identity\n- Name: Matt\n- Rules for r1:\n  - Matt lives in Berlin and is 40\n"
        "## Decisions\n- Never edit generated files:\n  - src/gen\n",
    )
    assert "Berlin" not in adds and "3 personal entries" in plan
    assert "Never edit generated files:" in adds and "src/gen" in adds


def test_code_and_rule_lines_are_listed_not_stored(tmp_path):
    adds, plan = plan_of(
        tmp_path,
        "## Decisions\n- Use uv\n* * *\n- - -\n```yaml\n- name: build\n# comment\n```\n"
        "```Always use uv```\n",
    )
    assert adds.count("+ decision") == 1
    for text in ("* * *", "- - -", "- name: build", "# comment", "```Always use uv```"):
        assert text in skipped(plan)


def test_a_bold_line_with_nothing_under_it_is_listed(tmp_path):
    _, plan = plan_of(tmp_path, "## Decisions\n- Use uv\n**Do not touch the legacy folder**\n")
    assert "**Do not touch the legacy folder**" in skipped(plan)


@pytest.mark.parametrize(
    ("line", "closed"), [("```Always use pip``` (really)", True), ("~~~Always use pip~~~", False)]
)
def test_a_fence_line_with_text_is_listed(tmp_path, line, closed):
    """A tilde fence may hold `~` in its language, so it opens a block that never closes here."""
    adds, plan = plan_of(tmp_path, f"## Decisions\n- Use uv\n{line}\n- Use ruff\n")
    assert line in skipped(plan)
    assert ("Use ruff" in adds) is closed


def test_a_long_fence_holds_an_inner_code_block(tmp_path):
    adds, plan = plan_of(
        tmp_path, "````markdown\n## Decisions\n- Use uv\n```bash\nls -la\n```\n- Use ruff\n````\n"
    )
    assert "Use uv" in adds and "Use ruff" in adds and "+ decision" in adds
    assert "ls -la" in skipped(plan)


def test_a_mask_keeps_the_marks_of_the_other_words():
    hindi = "\u0939\u093f\u0928\u094d\u0926\u0940"
    family = "\U0001f468\u200d\U0001f469"
    split = f"{TOKEN[:10]}\u200b{TOKEN[10:]}"
    assert mask(f"{hindi}: {TOKEN} {family}") == f"{hindi}: [secret: GitHub token] {family}"
    assert mask(f"{hindi} {split} {family}") == f"{hindi} [secret: GitHub token] {family}"


@pytest.mark.parametrize("mark", ["\u2028", "\u2029", "\ue000"])
def test_separators_and_private_marks_hide_no_secret(mark):
    assert TOKEN[10:] not in mask(f"ok {TOKEN[:10]}{mark}{TOKEN[10:]} end")


@pytest.mark.parametrize(
    "text",
    [
        "~~~ python ~~~\n- pip install x\n~~~\n",
        "```text\n- use uv\nmore\n",
        "````text\n- a\n```\n- b\n",
        "```bash\n    ```\n- pip install x\n```\n",
    ],
)
def test_odd_fences_write_nothing_from_inside(tmp_path, text):
    adds, _ = plan_of(tmp_path, text)
    assert "+ " not in adds


def test_a_split_label_keeps_the_marks_of_the_other_words():
    words = "cafe\u0301 \u0939\u093f\u0928\u094d\u0926\u0940 \U0001f468\u200d\U0001f469"
    assert mask(f"{words} pass\u200bword = hunter2x") == (
        f"{words} password = [secret: assigned secret]"
    )


@pytest.mark.parametrize(
    "text",
    [
        "## Notes\n- Run tests with uv\n    ```bash\n    - rm -rf build\n    ```\n- Ship weekly\n",
        "1. Run tests with uv\n\t```yaml\n\t- rm -rf build\n\t```\n2. Ship weekly\n",
    ],
)
def test_a_code_block_under_a_list_item_is_code(tmp_path, text):
    adds, plan = plan_of(tmp_path, text)
    assert "Run tests with uv" in adds and "Ship weekly" in adds
    assert "rm -rf build" not in adds and "rm -rf build" in skipped(plan)


def test_a_closer_closes_its_own_block_past_another_mark(tmp_path):
    adds, _ = plan_of(tmp_path, "```md\n- a\n~~~\n- b\n```\n- c\n")
    assert all(f"so today: {word}\n" in adds for word in "abc")
