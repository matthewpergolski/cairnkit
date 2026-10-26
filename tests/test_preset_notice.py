"""`memory check` says when a preset has rules that the memory does not hold yet."""

import json

from conftest import read_jsonl

from cairnkit.cli import main


def run(capsys, *args):
    capsys.readouterr()
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out + out.err


def drop_rule(memdir, key):
    """Make the memory look older: remove one preset rule from default.jsonl."""
    path = memdir / "facts" / "default.jsonl"
    keep = [r for r in read_jsonl(path) if r.get("preset_rule") != key]
    path.write_text("".join(json.dumps(r) + "\n" for r in keep))


def test_check_names_the_missing_rules_and_the_command(repo, capsys):
    assert main(["init", "--preset", "dev"]) == 0
    memdir = repo.parent / "proj.memory"
    drop_rule(memdir, "basic.search-first")
    code, out = run(capsys, "check")
    assert code == 0
    assert "new preset rules available: basic.search-first; run `memory preset add dev`" in out


def test_check_writes_nothing(repo, capsys):
    assert main(["init", "--preset", "dev"]) == 0
    memdir = repo.parent / "proj.memory"
    drop_rule(memdir, "basic.search-first")
    before = (memdir / "facts" / "default.jsonl").read_bytes()
    run(capsys, "check")
    assert (memdir / "facts" / "default.jsonl").read_bytes() == before


def test_preset_add_adds_it_and_the_note_goes(repo, capsys):
    assert main(["init", "--preset", "dev"]) == 0
    memdir = repo.parent / "proj.memory"
    drop_rule(memdir, "basic.search-first")
    code, out = run(capsys, "preset", "add", "dev")
    assert code == 0 and "basic.search-first" in out
    assert "new preset rules available" not in run(capsys, "check")[1]


def test_a_complete_memory_is_quiet(repo, capsys):
    assert main(["init", "--preset", "dev"]) == 0
    assert "new preset rules" not in run(capsys, "check")[1]


def test_a_memory_without_preset_rules_is_quiet(mem, capsys):
    assert "new preset rules" not in run(capsys, "check")[1]


def test_a_rule_that_a_person_ended_is_not_offered_again(repo, capsys):
    assert main(["init", "--preset", "dev"]) == 0
    memdir = repo.parent / "proj.memory"
    rule = next(
        r
        for r in read_jsonl(memdir / "facts" / "default.jsonl")
        if r.get("preset_rule") == "dev.ask"
    )
    assert main(["change", rule["id"], "--status", "wrong", "--reason", "No."]) == 0
    assert "new preset rules" not in run(capsys, "check")[1]


def test_a_basic_memory_names_the_basic_preset(repo, capsys):
    assert main(["init", "--preset", "basic"]) == 0
    drop_rule(repo.parent / "proj.memory", "basic.cite")
    out = run(capsys, "check")[1]
    assert "new preset rules available: basic.cite; run `memory preset add basic`" in out


def test_a_newly_detected_tool_is_offered(repo, capsys):
    assert main(["init", "--preset", "dev"]) == 0
    (repo / "package-lock.json").write_text("{}\n")
    out = run(capsys, "check")[1]
    assert "dev.lockfile" in out and "memory preset add dev" in out


def test_a_commits_memory_is_quiet(repo, capsys):
    assert main(["init", "--preset", "commits"]) == 0
    assert "new preset rules" not in run(capsys, "check")[1]
