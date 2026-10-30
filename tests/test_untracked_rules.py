"""Rules blocks stay untracked: never written into CLAUDE.md or AGENTS.md."""

from conftest import git

from cairnkit import instructions
from cairnkit.cli import main

START = instructions.START
END = instructions.END
HAND = "# Team rules\n\nUse uv.\n"
BLOCK = f"{START}\nold block\n{END}\n"


def test_write_instructions_never_puts_a_block_in_tracked_files(repo):
    (repo / "CLAUDE.md").write_text(HAND)
    (repo / "AGENTS.md").write_text("# Agents\n\nBe kind.\n")
    git(repo, "add", "CLAUDE.md", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "track hand rules")
    assert main(["init", "--write-instructions"]) == 0
    assert (repo / "CLAUDE.md").read_text() == HAND
    assert (repo / "AGENTS.md").read_text() == "# Agents\n\nBe kind.\n"
    assert START in (repo / "CLAUDE.local.md").read_text()
    git(repo, "check-ignore", "-q", "CLAUDE.local.md")
    assert git(repo, "status", "--porcelain") == ""


def test_shared_mode_is_gone(repo, capsys):
    code = main(["init", "--write-instructions=shared"])
    assert code != 0
    assert START not in ((repo / "CLAUDE.md").read_text() if (repo / "CLAUDE.md").exists() else "")
    assert not (repo / "CLAUDE.md").exists() or START not in (repo / "CLAUDE.md").read_text()


def test_migrate_moves_block_out_of_tracked_files_into_local(repo):
    (repo / "CLAUDE.md").write_text(HAND + BLOCK)
    (repo / "AGENTS.md").write_text("# Agents\n\nBe kind.\n")
    git(repo, "add", "CLAUDE.md", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "old shared block")
    assert main(["init", "--write-instructions"]) == 0
    claude = (repo / "CLAUDE.md").read_text()
    assert claude == HAND
    assert START not in claude
    assert (repo / "AGENTS.md").read_text() == "# Agents\n\nBe kind.\n"
    local = (repo / "CLAUDE.local.md").read_text()
    assert START in local and "old block" not in local
    assert instructions.block() in local
    git(repo, "check-ignore", "-q", "CLAUDE.local.md")


def test_migrate_leaves_hand_written_content_when_block_was_only_addition(repo):
    (repo / "AGENTS.md").write_text(HAND + BLOCK + "\nAfter.\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "agents with block")
    assert main(["init", "--write-instructions"]) == 0
    text = (repo / "AGENTS.md").read_text()
    assert text.startswith(HAND) and text.endswith("After.\n")
    assert START not in text
    assert START in (repo / "CLAUDE.local.md").read_text()


def test_tidy_promotes_into_local_not_tracked(repo, mem, capsys, monkeypatch):
    from conftest import make_fact, write_facts

    (repo / "CLAUDE.md").write_text(HAND)
    git(repo, "add", "CLAUDE.md")
    git(repo, "commit", "-q", "-m", "claude")
    assert main(["init", "--write-instructions"]) == 0
    fact = make_fact("f-20261001-0001", "Never clear the dev database blind.", pinned=True)
    write_facts(mem, [{**fact, "kind": "trap"}])
    monkeypatch.setenv("MEMORY_NOW", "2026-10-20T12:00:00+00:00")
    out = capsys.readouterr()
    assert main(["tidy"]) == 0
    out = capsys.readouterr().out
    import re

    [pid] = re.findall(r"\bp-[0-9a-f]{6}\b", out)
    assert main(["tidy", "--apply", pid]) == 0
    assert (repo / "CLAUDE.md").read_text() == HAND
    assert "Never clear the dev database blind." in (repo / "CLAUDE.local.md").read_text()
