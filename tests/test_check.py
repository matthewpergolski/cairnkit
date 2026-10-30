import json
import shutil

import pytest
from conftest import FIXTURES, add_worktree

from cairnkit.cli import main

GOOD = {
    "type": "fact",
    "id": "f-20261001-aaaa",
    "kind": "fact",
    "text": "A good fact.",
    "area": "x",
    "happened_at": "2026-10-01",
    "learned_at": "2026-10-01T00:00:00+00:00",
    "source": "session:2026-10-01",
    "basis": "seen",
    "status": "active",
    "writer": "main",
}


def write(mem, *records, name="main.jsonl"):
    lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
    (mem / "facts" / name).write_text("".join(line + "\n" for line in lines))


def run_check(capsys):
    capsys.readouterr()
    code = main(["check"])
    return code, capsys.readouterr().out


def test_no_memory_folder_is_skipped(repo, capsys):
    code, out = run_check(capsys)
    assert code == 0
    assert "skipped" in out


def test_example_file_passes(repo, mem, capsys):
    shutil.copy(FIXTURES / "example-facts.jsonl", mem / "facts" / "main.jsonl")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_prices.py").write_text("")
    code, out = run_check(capsys)
    assert code == 0, out
    assert "ok" in out


def change(**extra):
    return {
        "type": "change",
        "id": GOOD["id"],
        "at": "2026-10-02T00:00:00+00:00",
        "writer": "main",
        **extra,
    }


BAD_CASES = {
    "not valid JSON": ["{not json"],
    "missing field 'area'": [{k: v for k, v in GOOD.items() if k != "area"}],
    "is not one of": [{**GOOD, "basis": "hunch"}],
    "400": [{**GOOD, "text": "x" * 401}],
    "duplicate id": [GOOD, GOOD],
    "needs superseded_by": [GOOD, change(status="superseded", reason="r")],
    "unknown fact": [GOOD, change(id="f-20261001-ffff", status="wrong", reason="r")],
    "superseded_by f-20261001-ffff": [
        GOOD,
        change(status="superseded", reason="r", superseded_by="f-20261001-ffff"),
    ],
    "link to unknown": [{**GOOD, "links": [{"rel": "related", "id": "f-20261001-ffff"}]}],
    "held_by": [GOOD, change(status="promoted", reason="r", held_by="docs/gone.md")],
    "needs a reason": [GOOD, change(status="wrong")],
    "secret": [{**GOOD, "text": "password = hunter22xyz"}],
}


@pytest.mark.parametrize("needle", BAD_CASES)
def test_each_rule_is_reported(mem, capsys, needle):
    write(mem, *BAD_CASES[needle])
    code, out = run_check(capsys)
    assert code == 1, out
    assert needle in out


def test_missing_link_is_healed_when_memory_exists(repo, mem, capsys):
    (repo / "memory-bank").unlink()
    code, out = run_check(capsys)
    assert code == 0, out
    assert (repo / "memory-bank").resolve() == mem.resolve()
    assert "linked" in out


def test_broken_link_is_reported(repo, mem, capsys, tmp_path):
    (repo / "memory-bank").unlink()
    (repo / "memory-bank").symlink_to(tmp_path / "gone")
    code, out = run_check(capsys)
    assert code == 1
    assert "broken" in out or "points to" in out


def test_real_folder_in_a_worktree_is_reported(repo, mem, capsys):
    wt = add_worktree(repo, "feature-r")
    (wt / "memory-bank").mkdir()
    (wt / "memory-bank" / "x.md").write_text("x")
    code, out = run_check(capsys)
    assert code == 1
    assert "real folder" in out


def test_writer_mismatch_is_only_a_warning(mem, capsys):
    write(mem, {**GOOD, "writer": "other"})
    code, out = run_check(capsys)
    assert code == 0
    assert "warning" in out


RULE = "Write a failing test before you fix a bug, then make it pass."


def rule_fact(fid="f-20261001-0b01", text=RULE, **extra):
    return {**GOOD, "id": fid, "kind": "rule", "text": text, **extra}


def test_rule_in_an_instruction_file_is_a_warning(repo, mem, capsys):
    write(mem, rule_fact())
    (repo / "AGENTS.md").write_text(
        "# Agents\n\n- **Tests.** Write a failing test before you fix\n"
        "  a bug, then make it pass.\n"
    )
    code, out = run_check(capsys)
    assert code == 0, out
    assert "warning: AGENTS.md:3: repeats rule fact f-20261001-0b01" in out
    # The installed tool has no docs folder: point to the page on GitHub.
    url = "https://github.com/matthewpergolski/cairnkit/blob/main/docs/layering.md"
    assert f"{url}#if-you-have-duplicates" in out
    capsys.readouterr()
    assert main(["check", "--strict"]) == 1
    assert "error: AGENTS.md:3: repeats rule fact f-20261001-0b01" in capsys.readouterr().out


def test_local_instruction_file_is_checked_too(repo, mem, capsys):
    write(mem, rule_fact())
    (repo / "CLAUDE.local.md").write_text(f"Port 5174 here.\n\n{RULE.upper()}\n")
    _, out = run_check(capsys)
    assert "CLAUDE.local.md:3: repeats rule fact f-20261001-0b01" in out


@pytest.mark.parametrize(
    "records",
    [
        [{**GOOD, "text": RULE}],  # not a rule
        [rule_fact(text="Write a failing test after you fix a bug, then make it pass.")],
        [rule_fact(id=GOOD["id"]), change(status="expired", reason="r")],
    ],
)
def test_other_words_or_facts_are_not_flagged(repo, mem, capsys, records):
    write(mem, *records)
    (repo / "CLAUDE.md").write_text(f"{RULE}\n")
    _, out = run_check(capsys)
    assert "repeats rule fact" not in out


def test_the_block_that_memory_writes_is_not_a_duplicate(repo, capsys):
    assert main(["init", "--preset", "commits", "--write-instructions"]) == 0
    assert "cairnkit:start" in (repo / "CLAUDE.local.md").read_text()
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0, capsys.readouterr().out
    from cairnkit.rules import GUARDED

    (repo / "AGENTS.md").write_text(f"# Agents\n\n- {GUARDED}\n")
    lines = (repo / "AGENTS.md").read_text().splitlines()
    capsys.readouterr()
    assert main(["check", "--strict"]) == 1
    out = capsys.readouterr().out
    assert out.count("repeats rule fact") == 1
    assert f"error: AGENTS.md:{len(lines)}: repeats rule fact" in out


def test_a_start_marker_without_an_end_runs_to_the_end_of_the_file(repo, capsys):
    from cairnkit.instructions import END, START
    from cairnkit.rules import GUARDED

    assert main(["init", "--preset", "commits", "--write-instructions"]) == 0
    local = repo / "CLAUDE.local.md"
    text = local.read_text().replace(END + "\n", "")
    local.write_text(text)
    agents = f"# Agents\n\n- {GUARDED}\n\n{START}\ntruncated from a lost end\n"
    (repo / "AGENTS.md").write_text(agents)
    capsys.readouterr()
    assert main(["check", "--strict"]) == 1
    out = capsys.readouterr().out
    assert out.count("repeats rule fact") == 1
    assert "error: AGENTS.md:3: repeats rule fact" in out


@pytest.mark.parametrize(
    "line",
    ["Use [uv](https://docs.astral.sh/uv/).", "Use <code>uv</code>.", "Use <b class='x'>uv</b>."],
)
def test_link_targets_and_html_tags_do_not_count(repo, mem, capsys, line):
    write(mem, rule_fact(text="Use uv."))
    (repo / "AGENTS.md").write_text(f"- {line}\n")
    _, out = run_check(capsys)
    assert "AGENTS.md:1: repeats rule fact f-20261001-0b01" in out


FRIDAY = "Never deploy on Friday."


@pytest.mark.parametrize(
    "text",
    [
        f"# Agents\n\n<!-- old rules\n- {FRIDAY}\n-->\n",
        f"# Agents\n\n<!--\n- {FRIDAY}\n",  # the close is missing: it runs to the end
        f"# Agents\n\nKeep it short. <!-- not this:\n- {FRIDAY}\nend --> Done.\n",
    ],
)
def test_a_multi_line_comment_is_not_an_instruction(repo, mem, capsys, text):
    write(mem, rule_fact(text=FRIDAY))
    (repo / "AGENTS.md").write_text(text)
    _, out = run_check(capsys)
    assert "repeats rule fact" not in out


def test_a_line_after_a_closed_comment_still_counts(repo, mem, capsys):
    write(mem, rule_fact(text=FRIDAY))
    (repo / "AGENTS.md").write_text(f"<!--\nold\n-->\n- {FRIDAY}\n")
    _, out = run_check(capsys)
    assert "AGENTS.md:4: repeats rule fact f-20261001-0b01" in out


def test_a_line_that_starts_with_a_tag_is_read(repo, mem, capsys):
    write(mem, rule_fact(text="Use uv."))
    (repo / "AGENTS.md").write_text("# Agents\n\n<b>Use uv</b>\n")
    _, out = run_check(capsys)
    assert "AGENTS.md:3: repeats rule fact f-20261001-0b01" in out


@pytest.mark.parametrize(
    "line",
    [
        "Use [uv](https://example/a_(b)_guide).",
        "Use [uv](https://example/a_(b_(c))_d).",
        'Use [uv](https://example/(x) "A (title)").',
        'Use <span title="a > b">uv</span>.',
        "Use <span data-x='1 > 0' title=\"x\">uv</span>.",
    ],
)
def test_nested_link_targets_and_quoted_tag_attributes(repo, mem, capsys, line):
    write(mem, rule_fact(text="Use uv."))
    (repo / "AGENTS.md").write_text(f"- {line}\n")
    _, out = run_check(capsys)
    assert "AGENTS.md:1: repeats rule fact f-20261001-0b01" in out


@pytest.mark.parametrize(
    ("fact", "line"),
    [
        ("Run the tests. Fix the lint.", "Run the tests; fix the lint."),
        ("Run the tests; fix the lint.", "Run the tests. Fix the lint."),
        ("Run the tests. Fix the lint.", "Be brief. Run the tests, fix the lint! Then stop."),
    ],
)
def test_sentence_breaks_inside_a_match_do_not_count(repo, mem, capsys, fact, line):
    write(mem, rule_fact(text=fact))
    (repo / "AGENTS.md").write_text(f"- {line}\n")
    _, out = run_check(capsys)
    assert "AGENTS.md:1: repeats rule fact f-20261001-0b01" in out


@pytest.mark.parametrize(
    "line", ["Use uv for Python.", "Always use uv.", "Use uv tools. Be brief."]
)
def test_a_match_still_starts_and_ends_at_a_sentence_edge(repo, mem, capsys, line):
    write(mem, rule_fact(text="Use uv."))
    (repo / "AGENTS.md").write_text(f"- {line}\n")
    _, out = run_check(capsys)
    assert "repeats rule fact" not in out
