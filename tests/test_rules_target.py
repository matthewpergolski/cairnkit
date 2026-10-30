"""Rules block stays in CLAUDE.local.md; tracked files are never written."""

import pytest
from conftest import make_fact, write_facts

from cairnkit import harness_local, instructions
from cairnkit.cli import main

START = instructions.START
END = instructions.END
FILES = ("CLAUDE.md", "AGENTS.md", "CLAUDE.local.md", "AGENTS.local.md", *harness_local.rels())
HAND = "# Team rules\n\nUse uv.\n"


def blocks(repo):
    """How many blocks each rules file holds."""
    return {n: (repo / n).read_text().count(START) for n in FILES if (repo / n).exists()}


def run(args, capsys):
    capsys.readouterr()
    code = main(args)
    return code, capsys.readouterr().out


def test_shared_mode_is_refused(repo, capsys):
    code, out = run(["init", "--write-instructions=shared"], capsys)
    assert code == 1
    assert "error:" in out and "shared" in out.lower()
    assert not (repo / "CLAUDE.md").exists()
    assert not (repo / "CLAUDE.local.md").exists()


def test_local_write_leaves_hand_written_tracked_files_alone(repo):
    (repo / "CLAUDE.md").write_text(HAND)
    (repo / "AGENTS.md").write_text("# Agents\n\nBe kind.\n")
    assert main(["init", "--write-instructions"]) == 0
    assert (repo / "CLAUDE.md").read_text() == HAND
    assert (repo / "AGENTS.md").read_text() == "# Agents\n\nBe kind.\n"
    assert blocks(repo)["CLAUDE.local.md"] == 1


def test_migrate_moves_block_from_claude_md(repo, capsys):
    (repo / "CLAUDE.md").write_text(HAND + f"{START}\nold\n{END}\n")
    code, out = run(["init", "--write-instructions"], capsys)
    assert code == 0
    assert "remove the rules block from" in out and "CLAUDE.md" in out
    assert (repo / "CLAUDE.md").read_text() == HAND
    assert START not in (repo / "CLAUDE.md").read_text()
    assert instructions.block() in (repo / "CLAUDE.local.md").read_text()


def test_migrate_moves_block_from_agents_md(repo):
    (repo / "AGENTS.md").write_text(HAND + f"{START}\nold\n{END}\n\nAfter.\n")
    assert main(["init", "--write-instructions"]) == 0
    text = (repo / "AGENTS.md").read_text()
    assert text.startswith(HAND) and text.endswith("After.\n")
    assert START not in text
    assert START in (repo / "CLAUDE.local.md").read_text()


def test_instructions_file_must_be_untracked(repo):
    (repo / "docs").mkdir()
    (repo / "docs" / "R.md").write_text(HAND)
    from conftest import git

    git(repo, "add", "docs/R.md")
    git(repo, "commit", "-q", "-m", "track")
    assert main(["init", "--write-instructions", "--instructions-file", "docs/R.md"]) == 1
    assert (repo / "docs" / "R.md").read_text() == HAND


def test_instructions_file_untracked_is_allowed(repo):
    assert main(["init", "--write-instructions", "--instructions-file", "docs/R.md"]) == 0
    assert START in (repo / "docs" / "R.md").read_text()
    assert not (repo / "CLAUDE.local.md").exists()


SETUPS = {
    "empty": {},
    "agents": {"AGENTS.md": HAND},
    "claude": {"CLAUDE.md": HAND},
    "both": {"CLAUDE.md": HAND, "AGENTS.md": "# Agents\n"},
    "block in agents": {"CLAUDE.md": HAND, "AGENTS.md": f"{START}\nold\n{END}\n"},
}


@pytest.mark.parametrize("setup", sorted(SETUPS))
@pytest.mark.parametrize("command", ["init", "instructions"])
def test_the_block_appears_once_in_local_and_does_not_grow(repo, setup, command):
    for name, text in SETUPS[setup].items():
        (repo / name).write_text(text)
    assert main(["init"]) == 0
    args = [command, "--write-instructions"]
    assert main(args) == 0
    first = (repo / "CLAUDE.local.md").read_text()
    assert first.count(START) == 1
    for name in ("CLAUDE.md", "AGENTS.md"):
        if (repo / name).exists():
            assert START not in (repo / name).read_text()
    for _ in range(2):
        assert main(args) == 0
        assert main(["init", "--refresh"]) == 0
    assert (repo / "CLAUDE.local.md").read_text() == first


def test_dry_run_migrates_nothing_and_writes_nothing(repo, capsys):
    (repo / "AGENTS.md").write_text(HAND + f"{START}\nold\n{END}\n")
    code, out = run(["init", "--dry-run", "--write-instructions"], capsys)
    assert code == 0
    assert "would" in out and "AGENTS.md" in out
    assert (repo / "AGENTS.md").read_text() == HAND + f"{START}\nold\n{END}\n"
    assert not (repo / "CLAUDE.local.md").exists()


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


def test_refresh_migrates_tracked_then_updates_local(repo):
    assert main(["init"]) == 0
    old = f"# Mine\n\n{START}\nold\n{END}\n"
    (repo / "CLAUDE.local.md").write_text(old)
    (repo / "AGENTS.local.md").write_text(old)
    (repo / "AGENTS.md").write_text(old)
    assert main(["init", "--refresh"]) == 0
    for name in ("CLAUDE.local.md", "AGENTS.local.md"):
        text = (repo / name).read_text()
        assert text.startswith("# Mine\n\n") and instructions.block() in text
        assert text.count(START) == 1
    assert (repo / "AGENTS.md").read_text() == "# Mine\n\n"
    assert START not in (repo / "AGENTS.md").read_text()


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


def test_tidy_uses_claude_local_md(repo, mem, capsys, monkeypatch):
    (repo / "CLAUDE.md").write_text(HAND)
    (repo / "AGENTS.md").write_text("# Agents\n")
    assert main(["init", "--write-instructions"]) == 0
    promote(mem, capsys, monkeypatch)
    assert (repo / "CLAUDE.md").read_text() == HAND
    assert (repo / "AGENTS.md").read_text() == "# Agents\n"
    assert "Never clear the dev database blind." in (repo / "CLAUDE.local.md").read_text()
    assert held_by(mem) == "CLAUDE.local.md"


def test_tidy_keeps_a_rules_file_the_config_sets(repo, mem, capsys, monkeypatch):
    (mem / "config.toml").write_text('rules_file = "docs/RULES.md"\n')
    (repo / "CLAUDE.md").write_text(HAND)
    promote(mem, capsys, monkeypatch)
    assert "Never clear" in (repo / "docs" / "RULES.md").read_text()
    assert (repo / "CLAUDE.md").read_text() == HAND
    assert held_by(mem) == "docs/RULES.md"


def test_tidy_refuses_a_tracked_rules_file(repo, mem, capsys, monkeypatch):
    from conftest import git

    (mem / "config.toml").write_text('rules_file = "CLAUDE.md"\n')
    (repo / "CLAUDE.md").write_text(HAND)
    git(repo, "add", "CLAUDE.md")
    git(repo, "commit", "-q", "-m", "track")
    monkeypatch.setenv("MEMORY_NOW", "2026-10-20T12:00:00+00:00")
    rule_fact(mem)
    _, out = run(["tidy"], capsys)
    import re

    [pid] = re.findall(r"\bp-[0-9a-f]{6}\b", out)
    code, out = run(["tidy", "--apply", pid], capsys)
    assert code == 1
    assert "tracked" in out
    assert (repo / "CLAUDE.md").read_text() == HAND


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


def tracked(repo, *names):
    from conftest import git

    git(repo, "add", *names)
    git(repo, "commit", "-q", "-m", "track")


@pytest.mark.parametrize("target", ["AGENTS.md", "CLAUDE.md"])
def test_local_mode_refuses_a_link_to_a_tracked_file(repo, capsys, target):
    (repo / target).write_text(HAND)
    tracked(repo, target)
    (repo / "CLAUDE.local.md").symlink_to(target)
    code, out = run(["init", "--write-instructions"], capsys)
    assert code == 1
    assert "error:" in out and "tracked" in out and target in out
    assert (repo / target).read_text() == HAND
    code, out = run(["instructions", "--write-instructions"], capsys)
    assert code == 1 and (repo / target).read_text() == HAND


def test_local_mode_follows_a_link_to_an_untracked_file(repo):
    (repo / "mine.md").write_text("# Mine\n")
    (repo / "CLAUDE.local.md").symlink_to("mine.md")
    assert main(["init", "--write-instructions"]) == 0
    assert START in (repo / "mine.md").read_text()
    assert (repo / "CLAUDE.local.md").is_symlink()


@pytest.mark.parametrize("name", ["CLAUDE.md", "AGENTS.md", "CLAUDE.local.md"])
def test_a_symlink_loop_is_an_error_and_nothing_is_written(repo, capsys, name):
    assert main(["init"]) == 0
    (repo / name).symlink_to(name)
    before = sorted(p.name for p in repo.iterdir())
    code, out = run(["instructions", "--write-instructions"], capsys)
    assert code == 1
    assert "error:" in out and name in out and "loop" in out
    assert "Traceback" not in out
    assert sorted(p.name for p in repo.iterdir()) == before


def outside(tmp_path, text=HAND):
    far = tmp_path / "elsewhere"
    far.mkdir()
    (far / "rules.md").write_text(text)
    return far / "rules.md"


def test_local_mode_may_use_a_link_that_leaves_the_repo(repo, tmp_path):
    far = outside(tmp_path, "# Mine\n")
    (repo / "CLAUDE.local.md").symlink_to(far)
    assert main(["init", "--write-instructions"]) == 0
    assert START in far.read_text()


IMPORT = "@AGENTS.md\n\n"


def local_text(repo):
    return (repo / "CLAUDE.local.md").read_text()


def test_local_mode_imports_agents_md_when_it_is_the_only_shared_file(repo, capsys):
    (repo / "AGENTS.md").write_text(HAND)
    code, out = run(["init", "--write-instructions"], capsys)
    assert code == 0
    assert local_text(repo).startswith(IMPORT + START)
    assert (repo / "AGENTS.md").read_text() == HAND
    [note] = [x for x in out.splitlines() if "@AGENTS.md" in x]
    assert "CLAUDE.local.md" in note
    first = local_text(repo)
    for _ in range(2):
        assert main(["instructions", "--write-instructions"]) == 0
        assert main(["init", "--refresh"]) == 0
    assert local_text(repo) == first
    assert first.count("@AGENTS.md") == 1 and first.count(START) == 1
    _, out = run(["instructions", "--write-instructions"], capsys)
    assert "@AGENTS.md" not in out


def test_an_earlier_local_file_gets_the_import_on_the_next_write(repo):
    (repo / "AGENTS.md").write_text(HAND)
    (repo / "CLAUDE.local.md").write_text(f"# Mine\n\n{START}\nstale line\n{END}\n")
    assert main(["init", "--write-instructions"]) == 0
    text = local_text(repo)
    assert text.startswith(IMPORT + "# Mine\n\n" + START)
    assert "stale line" not in text


def test_an_import_the_user_already_has_is_not_repeated(repo):
    (repo / "AGENTS.md").write_text(HAND)
    (repo / "CLAUDE.local.md").write_text("# Mine\n\n@AGENTS.md\n")
    assert main(["init", "--write-instructions"]) == 0
    assert local_text(repo).count("@AGENTS.md") == 1
    assert local_text(repo).startswith("# Mine\n\n@AGENTS.md\n")


@pytest.mark.parametrize("home", ["CLAUDE.md", ".claude/CLAUDE.md"])
def test_no_import_when_claude_reads_a_claude_md_anyway(repo, home):
    (repo / "AGENTS.md").write_text(HAND)
    (repo / home).parent.mkdir(exist_ok=True)
    (repo / home).write_text(HAND)
    assert main(["init", "--write-instructions"]) == 0
    assert "@AGENTS.md" not in local_text(repo)


def test_no_import_without_an_agents_md(repo):
    assert main(["init", "--write-instructions"]) == 0
    assert "@AGENTS.md" not in local_text(repo)


def test_no_import_when_claude_local_md_is_agents_md(repo):
    (repo / "AGENTS.md").write_text(HAND)
    (repo / "CLAUDE.local.md").symlink_to("AGENTS.md")
    assert main(["init", "--write-instructions"]) == 0
    assert "@AGENTS.md" not in (repo / "AGENTS.md").read_text()


def test_dry_run_says_it_would_add_the_import_and_adds_nothing(repo, capsys):
    (repo / "AGENTS.md").write_text(HAND)
    code, out = run(["init", "--dry-run", "--write-instructions"], capsys)
    assert code == 0
    assert any("would" in x and "@AGENTS.md" in x for x in out.splitlines())
    assert not (repo / "CLAUDE.local.md").exists()


def test_harness_local_copies_are_written_and_excluded(repo):
    from conftest import git

    assert main(["init", "--write-instructions"]) == 0
    for target in harness_local.TARGETS:
        path = repo / target.rel
        assert path.is_file()
        assert START in path.read_text()
        git(repo, "check-ignore", "-q", target.rel)
    assert git(repo, "status", "--porcelain") == ""


def test_opencode_gap_is_documented():
    assert "OpenCode" in harness_local.OPENCODE_GAP
    assert "tracked" in harness_local.OPENCODE_GAP.lower()
