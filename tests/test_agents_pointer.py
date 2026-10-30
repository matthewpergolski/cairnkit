"""Codex reads tracked AGENTS.md; cairnkit adds one pointer line, never AGENTS.override.md."""

from conftest import git

from cairnkit import harness_local, instructions
from cairnkit.cli import main

POINTER = "Also read `CLAUDE.md`, and `CLAUDE.local.md` if it exists."
HAND = "# Team rules\n\nUse uv.\n"


def test_init_adds_agents_pointer_and_never_writes_override(repo):
    assert main(["init", "--write-instructions"]) == 0
    agents = repo / "AGENTS.md"
    assert agents.is_file()
    text = agents.read_text()
    assert POINTER in text
    assert instructions.START not in text
    assert "cairnkit" not in text.lower()
    assert not (repo / "AGENTS.override.md").exists()
    assert "AGENTS.override.md" not in harness_local.rels()


def test_agents_pointer_is_idempotent_and_keeps_hand_text(repo):
    (repo / "AGENTS.md").write_text(HAND)
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "agents")
    assert main(["init", "--write-instructions"]) == 0
    first = (repo / "AGENTS.md").read_text()
    assert first.startswith(HAND.rstrip()) or HAND.strip() in first
    assert first.count(POINTER) == 1
    assert main(["init", "--write-instructions"]) == 0
    second = (repo / "AGENTS.md").read_text()
    assert second == first
    assert second.count(POINTER) == 1


def test_init_removes_stale_agents_override(repo):
    (repo / "AGENTS.override.md").write_text("# stale override\n")
    assert main(["init", "--write-instructions"]) == 0
    assert not (repo / "AGENTS.override.md").exists()
    assert POINTER in (repo / "AGENTS.md").read_text()
