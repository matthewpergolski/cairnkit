"""Where the rules block goes: CLAUDE.local.md for local, the file the repo has for shared."""

import pytest
from conftest import make_fact, write_facts

from cairnkit import instructions
from cairnkit.cli import main

START = instructions.START
END = instructions.END
FILES = ("CLAUDE.md", "AGENTS.md", "CLAUDE.local.md", "AGENTS.local.md")
HAND = "# Team rules\n\nUse uv.\n"


def blocks(repo):
    """How many blocks each rules file holds."""
    return {n: (repo / n).read_text().count(START) for n in FILES if (repo / n).exists()}


def run(args, capsys):
    capsys.readouterr()
    code = main(args)
    return code, capsys.readouterr().out


def test_an_empty_repo_gets_claude_md_and_a_pointer(repo, capsys):
    code, out = run(["init", "--write-instructions=shared"], capsys)
    assert code == 0
    assert blocks(repo) == {"CLAUDE.md": 1, "AGENTS.md": 0}
    pointer = (repo / "AGENTS.md").read_text()
    assert "CLAUDE.md" in pointer and "CLAUDE.local.md" in pointer
    assert len(pointer.splitlines()) <= 5
    assert "CLAUDE.md" in out and "AGENTS.md" in out


def test_a_repo_with_only_agents_md_keeps_it_as_the_home(repo):
    (repo / "AGENTS.md").write_text(HAND)
    assert main(["init", "--write-instructions=shared"]) == 0
    assert blocks(repo) == {"AGENTS.md": 1}
    assert not (repo / "CLAUDE.md").exists()
    assert (repo / "AGENTS.md").read_text().startswith(HAND)


def test_a_repo_with_only_claude_md_gets_no_agents_md(repo):
    (repo / "CLAUDE.md").write_text(HAND)
    assert main(["instructions", "--write-instructions=shared"]) == 0
    assert blocks(repo) == {"CLAUDE.md": 1}
    assert not (repo / "AGENTS.md").exists()
    assert (repo / "CLAUDE.md").read_text().startswith(HAND)


def test_with_both_the_block_goes_to_claude_md_and_agents_md_is_not_edited(repo, capsys):
    (repo / "CLAUDE.md").write_text(HAND)
    (repo / "AGENTS.md").write_text("# Agents\n\nBe kind.\n")
    code, out = run(["init", "--write-instructions=shared"], capsys)
    assert code == 0
    assert blocks(repo) == {"CLAUDE.md": 1, "AGENTS.md": 0}
    assert (repo / "AGENTS.md").read_text() == "# Agents\n\nBe kind.\n"
    [hint] = [line for line in out.splitlines() if line.startswith("hint:")]
    assert "AGENTS.md" in hint and "CLAUDE.md" in hint


def test_no_hint_when_agents_md_already_mentions_claude_md(repo, capsys):
    (repo / "CLAUDE.md").write_text(HAND)
    (repo / "AGENTS.md").write_text("Rules live in CLAUDE.md.\n")
    _, out = run(["init", "--write-instructions=shared"], capsys)
    assert "hint:" not in out
    assert (repo / "AGENTS.md").read_text() == "Rules live in CLAUDE.md.\n"


def test_a_block_already_in_agents_md_is_refreshed_there_not_copied(repo):
    (repo / "CLAUDE.md").write_text(HAND)
    (repo / "AGENTS.md").write_text(f"# Agents\n\n{START}\nold text\n{END}\n")
    assert main(["init", "--write-instructions=shared"]) == 0
    assert blocks(repo) == {"CLAUDE.md": 0, "AGENTS.md": 1}
    assert "old text" not in (repo / "AGENTS.md").read_text()
    assert (repo / "CLAUDE.md").read_text() == HAND


def test_instructions_file_overrides_the_choice(repo):
    (repo / "CLAUDE.md").write_text(HAND)
    assert main(["init", "--write-instructions=shared", "--instructions-file", "docs/R.md"]) == 0
    assert START in (repo / "docs" / "R.md").read_text()
    assert (repo / "CLAUDE.md").read_text() == HAND
    assert not (repo / "AGENTS.md").exists()


SETUPS = {
    "empty": {},
    "agents": {"AGENTS.md": HAND},
    "claude": {"CLAUDE.md": HAND},
    "both": {"CLAUDE.md": HAND, "AGENTS.md": "# Agents\n"},
    "block in agents": {"CLAUDE.md": HAND, "AGENTS.md": f"{START}\nold\n{END}\n"},
}


@pytest.mark.parametrize("setup", sorted(SETUPS))
@pytest.mark.parametrize("command", ["init", "instructions"])
def test_the_block_appears_once_in_the_repo_and_does_not_grow(repo, setup, command):
    for name, text in SETUPS[setup].items():
        (repo / name).write_text(text)
    assert main(["init"]) == 0
    args = [command, "--write-instructions=shared"]
    assert main(args) == 0
    first = {n: (repo / n).read_text() for n in FILES if (repo / n).exists()}
    assert sum(blocks(repo).values()) == 1
    for _ in range(2):
        assert main(args) == 0
        assert main(["init", "--refresh"]) == 0
    assert {n: (repo / n).read_text() for n in FILES if (repo / n).exists()} == first
    assert all(t.count(END) <= 1 for t in first.values())


@pytest.mark.parametrize("setup", sorted(SETUPS))
def test_local_and_shared_blocks_stay_in_separate_files_and_do_not_grow(repo, setup):
    for name, text in SETUPS[setup].items():
        (repo / name).write_text(text)
    assert main(["init"]) == 0
    for _ in range(2):
        assert main(["init", "--write-instructions"]) == 0
        assert main(["init", "--write-instructions=shared"]) == 0
    count = blocks(repo)
    assert count["CLAUDE.local.md"] == 1
    assert sum(v for k, v in count.items() if k != "CLAUDE.local.md") == 1


def test_dry_run_says_what_it_found_and_would_do_and_writes_nothing(repo, capsys):
    (repo / "AGENTS.md").write_text(HAND)
    code, out = run(["init", "--dry-run", "--write-instructions=shared"], capsys)
    assert code == 0
    assert "would" in out and "AGENTS.md" in out
    assert (repo / "AGENTS.md").read_text() == HAND
    assert not (repo / "CLAUDE.md").exists()
    code, out = run(["init", "--dry-run", "--write-instructions=shared"], capsys)
    assert "would" in out and "CLAUDE.md" in out


def test_dry_run_in_an_empty_repo_plans_both_files_and_creates_none(repo, capsys):
    _, out = run(["init", "--dry-run", "--write-instructions=shared"], capsys)
    assert "would create the rules block in" in out and "would create" in out
    assert "AGENTS.md" in out
    assert not (repo / "CLAUDE.md").exists() and not (repo / "AGENTS.md").exists()


def test_the_report_names_the_files_it_found(repo, capsys):
    (repo / "CLAUDE.md").write_text(HAND)
    _, out = run(["instructions", "--write-instructions"], capsys)
    line = next(x for x in out.splitlines() if x.startswith("found:"))
    assert "CLAUDE.md" in line and "AGENTS.md" not in line
    assert "CLAUDE.local.md" in out


def test_an_old_local_block_gets_a_note_and_stays(repo, capsys):
    old = f"{START}\nold\n{END}\n"
    (repo / "AGENTS.local.md").write_text(old)
    code, out = run(["init", "--write-instructions"], capsys)
    assert code == 0
    assert (repo / "AGENTS.local.md").read_text() == old
    assert START in (repo / "CLAUDE.local.md").read_text()
    [note] = [x for x in out.splitlines() if x.startswith("note:") and "AGENTS.local.md" in x]
    assert "CLAUDE.local.md" in note and "by hand" in note


def test_no_note_without_an_old_block(repo, capsys):
    (repo / "AGENTS.local.md").write_text("mine\n")
    _, out = run(["init", "--write-instructions"], capsys)
    assert "AGENTS.local.md" not in out


def test_refresh_still_updates_old_and_new_block_files_in_place(repo):
    assert main(["init"]) == 0
    old = f"# Mine\n\n{START}\nold\n{END}\n"
    for name in ("CLAUDE.local.md", "AGENTS.local.md", "AGENTS.md"):
        (repo / name).write_text(old)
    assert main(["init", "--refresh"]) == 0
    for name in ("CLAUDE.local.md", "AGENTS.local.md", "AGENTS.md"):
        text = (repo / name).read_text()
        assert text.startswith("# Mine\n\n") and instructions.block() in text
        assert text.count(START) == 1


def rule_fact(mem):
    fact = make_fact("f-20261001-0001", "Never clear the dev database blind.", pinned=True)
    write_facts(mem, [{**fact, "kind": "trap"}])


def promote(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", "2026-10-20T12:00:00+00:00")
    rule_fact(mem)
    _, out = run(["tidy"], capsys)
    import re

    [pid] = re.findall(r"\bp-[0-9a-f]{6}\b", out)
    assert main(["tidy", "--apply", pid]) == 0
    capsys.readouterr()
    return pid


def held_by(mem):
    from conftest import read_jsonl

    return read_jsonl(mem / "facts" / "tidy.jsonl")[-1]["held_by"]


def test_tidy_uses_claude_md_when_it_exists(repo, mem, capsys, monkeypatch):
    (repo / "CLAUDE.md").write_text(HAND)
    (repo / "AGENTS.md").write_text("# Agents\n")
    promote(mem, capsys, monkeypatch)
    assert "Never clear the dev database blind." in (repo / "CLAUDE.md").read_text()
    assert (repo / "AGENTS.md").read_text() == "# Agents\n"
    assert held_by(mem) == "CLAUDE.md"


def test_tidy_uses_agents_md_when_it_is_the_only_file(repo, mem, capsys, monkeypatch):
    (repo / "AGENTS.md").write_text(HAND)
    promote(mem, capsys, monkeypatch)
    assert "Never clear the dev database blind." in (repo / "AGENTS.md").read_text()
    assert not (repo / "CLAUDE.md").exists()
    assert held_by(mem) == "AGENTS.md"


def test_tidy_defaults_to_claude_md_when_neither_exists(repo, mem, capsys, monkeypatch):
    promote(mem, capsys, monkeypatch)
    assert "Never clear the dev database blind." in (repo / "CLAUDE.md").read_text()
    assert held_by(mem) == "CLAUDE.md"


def test_tidy_keeps_a_rules_file_the_config_sets(repo, mem, capsys, monkeypatch):
    (mem / "config.toml").write_text('rules_file = "docs/RULES.md"\n')
    (repo / "CLAUDE.md").write_text(HAND)
    promote(mem, capsys, monkeypatch)
    assert "Never clear" in (repo / "docs" / "RULES.md").read_text()
    assert (repo / "CLAUDE.md").read_text() == HAND
    assert held_by(mem) == "docs/RULES.md"


def test_a_new_memory_does_not_pin_the_rules_file(repo):
    from cairnkit.config import load_config

    assert main(["init"]) == 0
    text = (repo.parent / "proj.memory" / "config.toml").read_text()
    assert not any(x.startswith("rules_file") for x in text.splitlines())
    assert load_config(repo.parent / "proj.memory")["rules_file"] is None


def test_the_help_names_the_new_files(capsys):
    for command in ("init", "instructions"):
        with pytest.raises(SystemExit):
            main([command, "--help"])
    out = capsys.readouterr().out
    assert "CLAUDE.local.md" in out and "AGENTS.local.md" not in out
