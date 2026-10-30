"""Rules blocks stay untracked: never written into CLAUDE.md or AGENTS.md."""

from conftest import git

from cairnkit import instructions
from cairnkit.cli import main

START = instructions.START
END = instructions.END
HAND = "# Team rules\n\nUse uv.\n"
BLOCK = f"{START}\nold block\n{END}\n"


def test_write_instructions_never_puts_a_block_in_tracked_files(repo):
    from cairnkit.harness_local import AGENTS_POINTER

    (repo / "CLAUDE.md").write_text(HAND)
    (repo / "AGENTS.md").write_text("# Agents\n\nBe kind.\n")
    git(repo, "add", "CLAUDE.md", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "track hand rules")
    assert main(["init", "--write-instructions"]) == 0
    assert (repo / "CLAUDE.md").read_text() == HAND
    agents = (repo / "AGENTS.md").read_text()
    assert agents.startswith("# Agents\n\nBe kind.\n")
    assert AGENTS_POINTER in agents
    assert START not in agents
    assert START in (repo / "CLAUDE.local.md").read_text()
    git(repo, "check-ignore", "-q", "CLAUDE.local.md")
    # Only the tracked pointer edit is dirty; local copies stay ignored.
    assert git(repo, "status", "--porcelain").strip() == "M AGENTS.md"


def test_shared_mode_is_gone(repo, capsys):
    code = main(["init", "--write-instructions=shared"])
    out = capsys.readouterr().out
    assert code == 1
    assert "error:" in out and "shared" in out.lower()
    assert not (repo / "CLAUDE.md").exists()
    assert not (repo / "CLAUDE.local.md").exists()


def test_migrate_moves_block_out_of_tracked_files_into_local(repo):
    from cairnkit.harness_local import AGENTS_POINTER

    (repo / "CLAUDE.md").write_text(HAND + BLOCK)
    (repo / "AGENTS.md").write_text("# Agents\n\nBe kind.\n")
    git(repo, "add", "CLAUDE.md", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "old shared block")
    assert main(["init", "--write-instructions"]) == 0
    claude = (repo / "CLAUDE.md").read_text()
    assert claude == HAND
    assert START not in claude
    agents = (repo / "AGENTS.md").read_text()
    assert agents.startswith("# Agents\n\nBe kind.\n")
    assert AGENTS_POINTER in agents and START not in agents
    local = (repo / "CLAUDE.local.md").read_text()
    assert START in local and "old block" not in local
    assert instructions.block() in local
    git(repo, "check-ignore", "-q", "CLAUDE.local.md")


def test_migrate_leaves_hand_written_content_when_block_was_only_addition(repo):
    from cairnkit.harness_local import AGENTS_POINTER

    (repo / "AGENTS.md").write_text(HAND + BLOCK + "\nAfter.\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "agents with block")
    assert main(["init", "--write-instructions"]) == 0
    text = (repo / "AGENTS.md").read_text()
    assert text.startswith(HAND) and "After.\n" in text
    assert text.rstrip().endswith(AGENTS_POINTER)
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
