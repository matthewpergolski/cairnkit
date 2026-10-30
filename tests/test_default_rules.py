from conftest import make_fact, read_jsonl, write_facts

from cairnkit.cli import main
from cairnkit.instructions import START


def test_init_preset_commits_seeds_default_rules(repo, capsys):
    assert main(["init", "--preset", "commits"]) == 0
    rules = read_jsonl(repo.parent / "proj.memory" / "facts" / "default.jsonl")
    assert len(rules) >= 2
    assert all(r["kind"] == "rule" and r["source"] == "default" for r in rules)
    text = " ".join(r["text"] for r in rules).lower()
    assert "co-authored-by" in text and "generated with" in text
    capsys.readouterr()
    assert main(["check"]) == 0


def test_seeding_is_idempotent_and_respects_removal(repo, capsys):
    assert main(["init", "--preset", "commits"]) == 0
    path = repo.parent / "proj.memory" / "facts" / "default.jsonl"
    first = read_jsonl(path)[0]["id"]
    assert main(["change", first, "--status", "wrong", "--reason", "Not for this project."]) == 0
    before = path.read_bytes() if path.exists() else b""
    assert main(["init", "--preset", "commits"]) == 0
    assert path.read_bytes() == before
    capsys.readouterr()
    main(["load"])
    assert read_jsonl(path)[0]["text"] not in capsys.readouterr().out


def test_no_default_rules_flag(repo):
    assert main(["init", "--no-default-rules"]) == 0
    assert not (repo.parent / "proj.memory" / "facts" / "default.jsonl").exists()


def test_load_shows_rules_first(repo, capsys):
    assert main(["init", "--preset", "commits"]) == 0
    mem = repo.parent / "proj.memory"
    write_facts(mem, [make_fact("f-20261001-0001", "A trap about deploys.", kind="trap")])
    capsys.readouterr()
    main(["load", "--budget", "40"])
    out = capsys.readouterr().out
    assert "## Advisory rules" in out
    assert out.index("## Advisory rules") < out.index("## Long-term")
    assert "Co-authored-by" in out


def test_kind_rule_can_be_added(mem, capsys):
    args = [
        "add",
        "Run the formatter before each commit.",
        "--kind",
        "rule",
        "--area",
        "git",
        "--basis",
        "told",
        "--source",
        "person:owner",
    ]
    assert main(args) == 0


def test_instructions_command_writes_the_local_block(repo, capsys):
    (repo / "AGENTS.md").write_text("# Team rules\n\nUse tabs.\n")
    assert main(["instructions", "--write-instructions"]) == 0
    assert main(["instructions", "--write-instructions"]) == 0
    assert (repo / "AGENTS.md").read_text() == "# Team rules\n\nUse tabs.\n"
    text = (repo / "CLAUDE.local.md").read_text()
    assert text.count(START) == 1
    assert "Co-authored-by" in text and "Generated with" in text


def test_instructions_block_lists_the_commit_rules(capsys):
    main(["instructions"])
    out = capsys.readouterr().out
    assert "Co-authored-by" in out and "Generated with" in out


def test_rules_stay_in_memory_unless_asked(repo, capsys):
    (repo / "AGENTS.md").write_text("# Team rules\n")
    assert main(["init"]) == 0
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    assert (repo / "AGENTS.md").read_text() == "# Team rules\n"
    assert not (repo / ".githooks").exists()
    assert not (repo / "AGENTS.local.md").exists()
    assert not (repo / "CLAUDE.local.md").exists()
