"""Rewrite old-layout paths, and find the lines that need a person or an agent."""

from cairnkit.migrate_refs import judgment_items, rewrite_text

HAVE = {"status.md", "decisions.md", "howto", "howto/x.md", "brief.md"}


def has(rel: str) -> bool:
    return rel.rstrip("/") in HAVE


def rw(text: str) -> tuple[str, int]:
    return rewrite_text(text, has)


def test_a_file_path_moves_under_notes():
    assert rw("See memory-bank/status.md now.") == ("See memory-bank/notes/status.md now.", 1)


def test_a_nested_path_and_a_folder_move_under_notes():
    text = "`memory-bank/howto/x.md` and the folder memory-bank/howto/ here"
    new, count = rw(text)
    assert new == "`memory-bank/notes/howto/x.md` and the folder memory-bank/notes/howto/ here"
    assert count == 2


def test_trailing_punctuation_stays_outside_the_path():
    assert rw("(memory-bank/status.md).")[0] == "(memory-bank/notes/status.md)."
    assert rw("see memory-bank/status.md, then memory-bank/brief.md.")[1] == 2


def test_paths_in_code_fences_and_inline_code_move_too():
    text = "```sh\ncat memory-bank/decisions.md\n```\n`memory-bank/brief.md`\n"
    new, count = rw(text)
    assert "memory-bank/notes/decisions.md" in new and "memory-bank/notes/brief.md" in new
    assert count == 2


def test_new_layout_paths_are_left_alone():
    text = (
        "memory-bank/notes/status.md memory-bank/facts/main.jsonl memory-bank/proposals/x.md "
        "memory-bank/branches/a.md memory-bank/config.toml memory-bank/README.md"
    )
    assert rw(text) == (text, 0)


def test_a_path_with_no_target_is_left_alone():
    text = "memory-bank/gone.md"
    assert rw(text) == (text, 0)


def test_bare_folder_and_other_names_are_left_alone():
    text = "`memory-bank/` is local. See docs/working/memory-bank.md and my-memory-bank/status.md."
    assert rw(text) == (text, 0)


def test_a_second_rewrite_changes_nothing():
    once, _ = rw("memory-bank/status.md and memory-bank/howto/x.md")
    assert rw(once) == (once, 0)


def test_checker_line_is_an_item_with_a_suggestion():
    items = judgment_items(
        "CLAUDE.md", "Intro\nRun `uv run tools/check_memory.py` at the start.\n", has
    )
    assert [(i.file, i.line, i.kind) for i in items] == [("CLAUDE.md", 2, "checker")]
    assert "Run `memory check` at the start." in items[0].suggestion
    assert "check_memory" in items[0].reason


def test_a_doc_named_for_the_old_folder_is_an_item():
    items = judgment_items("CLAUDE.md", "Read docs/working/memory-bank.md first.\n", has)
    assert [i.kind for i in items] == ["old-doc"]


def test_an_unresolved_old_path_is_an_item():
    items = judgment_items("a.md", "See memory-bank/gone.md.\n", has)
    assert [i.kind for i in items] == ["old-path"]


def test_a_bare_folder_mention_and_a_new_path_are_not_items():
    text = "`memory-bank/` is local.\nSee memory-bank/notes/status.md.\n"
    assert judgment_items("a.md", text, has) == []


def test_a_file_named_for_the_old_folder_is_an_item_for_the_whole_file():
    items = judgment_items("docs/working/memory-bank.md", "# Notes\nplain text\n", has)
    assert [(i.line, i.kind) for i in items] == [(1, "old-doc-file")]


def test_suggestion_keeps_the_backticks_around_a_bare_checker_path():
    items = judgment_items("a.md", "`tools/check_memory.py` fails when a note is old.\n", has)
    assert items[0].suggestion == "`memory check` fails when a note is old."
    items = judgment_items("a.md", "The numbers are in `tools/check_memory.py`. Then stop.\n", has)
    assert items[0].suggestion == "The numbers are in `memory check`. Then stop."
