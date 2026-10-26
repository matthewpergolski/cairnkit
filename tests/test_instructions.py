from conftest import git

from cairnkit.cli import main

START = "<!-- cairnkit:start -->"
END = "<!-- cairnkit:end -->"


def test_instructions_cover_the_rules(capsys):
    assert main(["instructions"]) == 0
    out = capsys.readouterr().out
    for needle in (
        "memory add",
        "--short",
        "superseded",
        "expired",
        "wrong",
        "secret",
        "by hand",
        "memory load",
    ):
        assert needle in out, needle


def test_init_does_not_write_instructions_by_default(repo):
    assert main(["init"]) == 0
    assert not (repo / "AGENTS.md").exists()


def test_write_instructions_adds_one_marked_block(repo):
    (repo / "AGENTS.md").write_text("# Rules\n\nBe kind.\n")
    assert main(["init", "--write-instructions=shared"]) == 0
    assert main(["init", "--write-instructions=shared"]) == 0
    text = (repo / "AGENTS.md").read_text()
    assert text.startswith("# Rules\n\nBe kind.\n")
    assert text.count(START) == 1 and text.count(END) == 1
    assert "memory add" in text


def test_write_instructions_replaces_an_old_block(repo):
    (repo / "AGENTS.md").write_text(f"top\n{START}\nold text\n{END}\nbottom\n")
    assert main(["init", "--write-instructions=shared"]) == 0
    text = (repo / "AGENTS.md").read_text()
    assert "old text" not in text
    assert text.startswith("top\n") and text.endswith("bottom\n")


def test_instructions_file_can_be_chosen(repo):
    assert (
        main(["init", "--write-instructions=shared", "--instructions-file", "docs/RULES.md"]) == 0
    )
    assert START in (repo / "docs" / "RULES.md").read_text()


def test_dry_run_does_not_write_instructions(repo):
    assert main(["init", "--dry-run", "--write-instructions"]) == 0
    assert not (repo / "AGENTS.md").exists()


def test_default_writes_a_local_ignored_file(repo):
    (repo / "AGENTS.md").write_text("# Shared rules\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "rules")
    assert main(["init", "--write-instructions"]) == 0
    assert (repo / "AGENTS.md").read_text() == "# Shared rules\n"
    local = repo / "AGENTS.local.md"
    assert START in local.read_text()
    assert "AGENTS.local.md" in (repo / ".git" / "info" / "exclude").read_text().splitlines()
    git(repo, "check-ignore", "-q", "AGENTS.local.md")
    assert git(repo, "status", "--porcelain") == ""


def test_local_file_can_be_chosen(repo):
    assert main(["init", "--write-instructions", "--instructions-file", "CLAUDE.local.md"]) == 0
    assert START in (repo / "CLAUDE.local.md").read_text()
    git(repo, "check-ignore", "-q", "CLAUDE.local.md")


def test_text_outside_the_block_is_never_changed(repo):
    body = "# Rules\n\nKeep this.\n"
    (repo / "AGENTS.md").write_text(body + START + "\nold\n" + END + "\n\nAfter.\n")
    assert main(["init", "--write-instructions=shared"]) == 0
    text = (repo / "AGENTS.md").read_text()
    assert text.startswith(body) and text.endswith("\nAfter.\n")


def test_local_mode_refuses_a_tracked_file(repo):
    (repo / "AGENTS.md").write_text("# Shared rules\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "rules")
    assert main(["init", "--write-instructions", "--instructions-file", "AGENTS.md"]) == 1
    assert (repo / "AGENTS.md").read_text() == "# Shared rules\n"


def test_kinds_line_lists_every_kind(capsys):
    from cairnkit.schema import BASES, KINDS

    main(["instructions"])
    out = capsys.readouterr().out
    [line] = [x for x in out.splitlines() if "Kinds:" in x]
    assert line.strip() == f"Kinds: {', '.join(KINDS)}. Basis: {', '.join(BASES)}."
