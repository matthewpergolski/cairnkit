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
    agents = (repo / "AGENTS.md").read_text()
    assert agents.startswith("# Agents\n\nBe kind.\n")
    assert START not in agents
    assert START in (repo / "CLAUDE.local.md").read_text()
    git(repo, "check-ignore", "-q", "CLAUDE.local.md")
    # Only the tracked pointer edit is dirty; local copies stay ignored.
    assert git(repo, "status", "--porcelain").strip() == ""


def test_shared_mode_is_gone(repo, capsys):
    code = main(["init", "--write-instructions=shared"])
    out = capsys.readouterr().out
    assert code == 1
    assert "error:" in out and "shared" in out.lower()
    assert not (repo / "CLAUDE.md").exists()
    assert not (repo / "CLAUDE.local.md").exists()


def test_a_tracked_block_stays_and_the_rules_go_local(repo):
    (repo / "CLAUDE.md").write_text(HAND + BLOCK)
    (repo / "AGENTS.md").write_text("# Agents\n\nBe kind.\n")
    git(repo, "add", "CLAUDE.md", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "old shared block")
    assert main(["init", "--write-instructions"]) == 0
    assert (repo / "CLAUDE.md").read_text() == HAND + BLOCK  # a tracked file does not change
    agents = (repo / "AGENTS.md").read_text()
    assert agents.startswith("# Agents\n\nBe kind.\n")
    assert START not in agents
    local = (repo / "CLAUDE.local.md").read_text()
    assert START in local and "old block" not in local
    assert instructions.block() in local
    git(repo, "check-ignore", "-q", "CLAUDE.local.md")


def test_a_tracked_file_with_a_block_and_hand_text_stays_as_it_was(repo):
    (repo / "AGENTS.md").write_text(HAND + BLOCK + "\nAfter.\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "agents with block")
    assert main(["init", "--write-instructions"]) == 0
    assert (repo / "AGENTS.md").read_text() == HAND + BLOCK + "\nAfter.\n"
    assert START in (repo / "CLAUDE.local.md").read_text()
