"""Rule presets: `memory init --preset NAME` and `memory preset list|show|add`."""

from pathlib import Path

import pytest
from conftest import DEV_KEYS, make_fact, read_jsonl, write_facts

from cairnkit.cli import main
from cairnkit.rules import DEFAULT_RULES
from cairnkit.schema import validate_record


def facts(memdir: Path) -> list[dict]:
    path = memdir / "facts" / "default.jsonl"
    return [r for r in read_jsonl(path) if r["type"] == "fact"] if path.exists() else []


def keys(memdir: Path) -> list[str]:
    return [r.get("preset_rule") for r in facts(memdir)]


def memdir_of(repo: Path) -> Path:
    return repo.parent / "proj.memory"


def run(capsys, *args) -> tuple[int, str]:
    capsys.readouterr()
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out + out.err


def test_init_without_preset_adds_no_rule_facts(repo, capsys):
    code, out = run(capsys, "init")
    assert code == 0
    assert facts(memdir_of(repo)) == []
    assert "rule fact" not in out


def test_commits_rules_can_still_be_added_by_hand(repo, capsys):
    assert main(["init"]) == 0
    code, out = run(capsys, "preset", "add", "commits")
    assert code == 0 and "add 3 rule fact(s)" in out
    rules = facts(memdir_of(repo))
    assert [r["text"] for r in rules] == DEFAULT_RULES
    assert all(r["source"] == "default" and r["writer"] == "default" for r in rules)
    assert keys(memdir_of(repo)) == ["commits.co-author", "commits.generated", "commits.author"]


def test_no_default_rules_is_the_none_preset(repo, tmp_path):
    assert main(["init", "--no-default-rules"]) == 0
    assert facts(memdir_of(repo)) == []
    other = tmp_path / "other"
    other.mkdir()
    assert main(["init", "--preset", "none", "--path", str(other / "m")]) == 0
    assert not (other / "m" / "facts" / "default.jsonl").exists()


def test_init_preset_basic_seeds_basic_rules_only(repo):
    assert main(["init", "--preset", "basic"]) == 0
    got = keys(memdir_of(repo))
    assert got and all(k.startswith("basic.") for k in got)
    assert "basic.cite" in got
    assert all(r["source"] == "preset:basic" for r in facts(memdir_of(repo)))


def test_preset_dev_includes_commits_and_shared_basic_rules(repo):
    assert main(["init", "--preset", "dev"]) == 0
    got = keys(memdir_of(repo))
    assert {"commits.co-author", "commits.generated", "commits.author"} <= set(got)
    assert {"basic.files", "basic.commands", "basic.secrets", "basic.search-first"} <= set(got)
    assert "basic.cite" not in got
    assert {"dev.verify", "dev.tests", "dev.git"} <= set(got)
    sources = {r["preset_rule"]: r["source"] for r in facts(memdir_of(repo))}
    assert sources["commits.author"] == "default"
    assert sources["basic.files"] == "preset:basic"
    assert sources["dev.tests"] == "preset:dev"


def test_dev_preset_holds_only_generic_rules():
    from cairnkit.presets import resolve

    assert {r.key for r in resolve(["dev"])} == DEV_KEYS


OLD_DEV_TOOL_KEYS = ("dev.uv", "dev.ruff", "dev.bun", "dev.biome", "dev.pins")


def test_memory_with_old_dev_tool_rules_keeps_them(repo, capsys):
    import tomllib

    from conftest import FIXTURES

    assert main(["init", "--preset", "dev"]) == 0
    memdir = memdir_of(repo)
    tools = tomllib.loads((FIXTURES / "tools_preset.toml").read_text())["rule"]
    texts = {"dev." + r["key"].split(".")[1]: r["text"] for r in tools}
    assert set(texts) == set(OLD_DEV_TOOL_KEYS)
    old = [
        make_fact(
            f"f-20260901-0{n}aa",
            texts[key],
            kind="rule",
            source="preset:dev",
            basis="told",
            writer="default",
            preset_rule=key,
        )
        for n, key in enumerate(OLD_DEV_TOOL_KEYS)
    ]
    write_facts(memdir, old, name="default.jsonl")
    path = memdir / "facts" / "default.jsonl"
    before = path.read_bytes()
    code, out = run(capsys, "load")
    assert code == 0
    assert all(text in out for text in texts.values())
    code, out = run(capsys, "preset", "add", "dev")
    assert code == 0 and "Nothing to add." in out
    assert path.read_bytes() == before
    assert all(keys(memdir).count(key) == 1 for key in OLD_DEV_TOOL_KEYS)
    for args in (("check",), ("check", "--strict")):
        code, out = run(capsys, *args)
        assert code == 0, out
        assert "warning" not in out and "note: new preset rules" not in out
        assert not any(key in out for key in OLD_DEV_TOOL_KEYS)


def test_presets_stack_without_duplicates(repo):
    assert main(["init", "--preset", "basic", "--preset", "dev"]) == 0
    got = keys(memdir_of(repo))
    assert len(got) == len(set(got))
    assert "basic.cite" in got and "dev.verify" in got and "commits.author" in got


def test_preset_add_to_existing_memory_adds_only_missing_keys(repo, capsys):
    assert main(["init", "--preset", "commits"]) == 0
    path = memdir_of(repo) / "facts" / "default.jsonl"
    before = path.read_bytes()
    code, out = run(capsys, "preset", "add", "dev")
    assert code == 0
    assert path.read_bytes().startswith(before)
    got = keys(memdir_of(repo))
    assert got.count("commits.co-author") == 1
    assert "dev.verify" in got
    assert "commits.co-author: already in memory" in out
    after = path.read_bytes()
    code, out = run(capsys, "preset", "add", "dev")
    assert code == 0 and path.read_bytes() == after
    assert keys(memdir_of(repo)) == got
    assert "Nothing to add." in out


def test_preset_add_skips_rule_ended_by_person(repo, capsys):
    assert main(["init", "--preset", "basic"]) == 0
    ids = {r["preset_rule"]: r["id"] for r in facts(memdir_of(repo))}
    reason = ["--reason", "Not for this project."]
    assert main(["change", ids["basic.cite"], "--status", "wrong", *reason]) == 0
    assert main(["change", ids["basic.files"], "--status", "expired", *reason]) == 0
    code, out = run(capsys, "preset", "add", "basic")
    assert code == 0
    got = keys(memdir_of(repo))
    assert got.count("basic.cite") == 1 and got.count("basic.files") == 1
    assert "basic.cite: ended (wrong); not added again" in out


def test_preset_add_skips_rule_with_same_text_written_by_hand(mem, capsys):
    from cairnkit.presets import load_preset

    text = next(r.text for r in load_preset("basic").rules if r.key == "basic.privacy")
    hand = make_fact("f-20261001-0abc", "  " + text.upper().rstrip(".") + " ", kind="rule")
    write_facts(mem, [hand])
    code, out = run(capsys, "preset", "add", "basic")
    assert code == 0
    assert "basic.privacy" not in keys(mem)
    assert "basic.privacy: same text as rule f-20261001-0abc" in out


def test_plain_init_does_not_add_commits_rules_to_a_preset_memory(repo):
    assert main(["init", "--preset", "basic"]) == 0
    assert main(["init"]) == 0
    assert not any(k.startswith("commits.") for k in keys(memdir_of(repo)))


def test_preset_rule_record_passes_validate_record(repo, capsys):
    assert main(["init", "--preset", "dev", "--preset", "basic"]) == 0
    for rec in facts(memdir_of(repo)):
        assert validate_record(rec) == []
        assert rec["kind"] == "rule" and rec["scope"] == "long" and rec["basis"] == "told"
    code, out = run(capsys, "check", "--strict")
    assert code == 0, out


def test_plain_folder_preset_basic_works_without_git(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    plain = home / "notes"
    plain.mkdir(parents=True)
    (plain / "letter.txt").write_text("hello\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(plain)
    assert main(["init", "--preset", "basic"]) == 0
    got = keys(home / "notes.memory")
    assert "basic.files" in got and not any(k.startswith("commits.") for k in got)
    code, out = run(capsys, "load")
    assert code == 0 and "Ask before you delete" in out


def test_dry_run_lists_preset_rules_and_changes_nothing(repo, capsys):
    code, out = run(capsys, "init", "--preset", "dev", "--dry-run")
    assert code == 0
    assert "would add" in out and "dev.verify" in out and "commits.co-author" in out
    assert not memdir_of(repo).exists()
    assert main(["init", "--preset", "commits"]) == 0
    path = memdir_of(repo) / "facts" / "default.jsonl"
    before = path.read_bytes()
    code, out = run(capsys, "preset", "add", "dev", "--dry-run")
    assert code == 0 and "would add" in out and "dev.verify" in out
    assert path.read_bytes() == before


def test_preset_list_and_show(capsys):
    code, out = run(capsys, "preset", "list")
    assert code == 0
    for name in ("commits", "basic", "dev"):
        assert name in out
    code, out = run(capsys, "preset", "show", "dev")
    assert code == 0
    assert "dev.verify" in out and "commits.co-author" in out and "basic.files" in out


def test_unknown_preset_name_errors_and_changes_nothing(repo, capsys):
    code, out = run(capsys, "init", "--preset", "nope")
    assert code == 1
    assert "unknown preset 'nope'" in out and "basic" in out
    assert not memdir_of(repo).exists()
    assert not (repo / "memory-bank").exists()
    assert main(["init", "--preset", "commits"]) == 0
    before = (memdir_of(repo) / "facts" / "default.jsonl").read_bytes()
    code, out = run(capsys, "preset", "add", "nope")
    assert code == 1
    assert (memdir_of(repo) / "facts" / "default.jsonl").read_bytes() == before
    code, out = run(capsys, "init", "--preset", "none", "--preset", "basic")
    assert code == 1 and "none" in out


TEMPLATE_PRESET = """\
summary = "Tool rules of a template."

[[rule]]
key = "tmpl.uv"
area = "python"
tags = ["python", "uv"]
text = "Manage Python with uv. Never use pip."

[[rule]]
key = "tmpl.bun"
area = "javascript"
when = "bun"
text = "Use Bun for JavaScript here."
"""


def test_preset_add_file_adds_the_rules_of_a_project_file(repo, capsys):
    preset = repo / "agents" / "preset.toml"
    preset.parent.mkdir()
    preset.write_text(TEMPLATE_PRESET)
    assert main(["init"]) == 0
    path = memdir_of(repo) / "facts" / "default.jsonl"
    code, out = run(capsys, "preset", "add", "--file", "agents/preset.toml", "--dry-run")
    assert code == 0 and "would add 1 rule fact(s)" in out and "tmpl.uv" in out
    assert not path.exists()
    code, out = run(capsys, "preset", "add", "commits", "--file", "agents/preset.toml")
    assert code == 0 and "add 4 rule fact(s)" in out
    assert "tmpl.bun: not detected" in out
    rules = {r["preset_rule"]: r for r in facts(memdir_of(repo))}
    assert set(rules) == {"commits.co-author", "commits.generated", "commits.author", "tmpl.uv"}
    assert rules["tmpl.uv"]["source"] == "preset:tmpl"
    assert rules["tmpl.uv"]["text"] == "Manage Python with uv. Never use pip."
    assert all(validate_record(r) == [] for r in rules.values())
    before = path.read_bytes()
    code, out = run(capsys, "preset", "add", "--file", str(preset))
    assert code == 0 and "Nothing to add." in out and path.read_bytes() == before
    reason = ["--reason", "Not for this project."]
    assert main(["change", rules["tmpl.uv"]["id"], "--status", "wrong", *reason]) == 0
    code, out = run(capsys, "preset", "add", "--file", str(preset))
    assert code == 0 and "tmpl.uv: ended (wrong); not added again" in out
    assert keys(memdir_of(repo)).count("tmpl.uv") == 1
    code, out = run(capsys, "check", "--strict")
    assert code == 0 and "tmpl" not in out


def test_preset_add_file_runs_detection_for_its_rules(repo, capsys):
    (repo / "bun.lock").write_text("{}\n")
    (repo / "preset.toml").write_text(TEMPLATE_PRESET)
    assert main(["init"]) == 0
    code, out = run(capsys, "preset", "add", "--file", "preset.toml")
    assert code == 0 and "tmpl.bun: advisory (bun.lock)" in out
    assert set(keys(memdir_of(repo))) == {"tmpl.uv", "tmpl.bun"}


def test_preset_add_file_skips_a_second_rule_with_the_same_text(repo, capsys):
    (repo / "preset.toml").write_text(
        '[[rule]]\nkey = "tmpl.a"\narea = "code"\ntext = "Run the checks."\n'
        '[[rule]]\nkey = "tmpl.b"\narea = "code"\ntext = "  run the CHECKS "\n'
    )
    assert main(["init"]) == 0
    code, out = run(capsys, "preset", "add", "--file", "preset.toml")
    assert code == 0 and "add 1 rule fact(s)" in out
    assert "tmpl.b: same text as rule tmpl.a" in out
    assert keys(memdir_of(repo)) == ["tmpl.a"]


def test_preset_add_file_skips_a_rule_with_the_text_of_a_preset_rule(repo, capsys):
    from cairnkit.presets import load_preset

    text = next(r.text for r in load_preset("commits").rules if r.key == "commits.author")
    (repo / "preset.toml").write_text(f'[[rule]]\nkey = "tmpl.a"\narea = "code"\ntext = "{text}"\n')
    assert main(["init"]) == 0
    code, out = run(capsys, "preset", "add", "commits", "--file", "preset.toml")
    assert code == 0 and "add 3 rule fact(s)" in out
    assert "tmpl.a: same text as rule commits.author" in out
    assert "tmpl.a" not in keys(memdir_of(repo))


RULE = '[[rule]]\nkey = "tmpl.a"\narea = "code"\ntext = "Rule A."\n'
SECRET = "AKIA" + "A" * 16


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (None, "cannot read it"),
        ("key = \n", "not valid TOML"),
        ('summary = "No rules."\n', "has no [[rule]]"),
        ('[[rule]]\nkey = "tmpl.a"\narea = "code"\n', "rule tmpl.a needs text"),
        (RULE.replace("tmpl.a", "uv"), "key 'uv' is not <prefix>.<name>"),
        (RULE.replace("tmpl.a", "dev.uv"), "prefix 'dev' is the name of a built-in preset"),
        (RULE + RULE.replace("tmpl.a", "other.b"), "keys use more than one prefix"),
        (RULE + RULE, "key tmpl.a is used twice"),
        (RULE + 'enforcedby = "lint:ruff"\n', "unknown field 'enforcedby'"),
        ('sumary = "x"\n' + RULE, "unknown field 'sumary'"),
        (RULE + 'when = "pytest"\n', "unknown detection name 'pytest'"),
        (RULE + 'enforced_by = "lint:ruff"\n', "enforced_by needs enforce_when"),
        (RULE + "tags = [1]\n", "tags must be a list of strings"),
        (RULE.replace("Rule A.", SECRET), "looks like a secret"),
        (RULE.replace("Rule A.", "x" * 401), "rule tmpl.a: text has 401 characters; the limit"),
        (
            RULE + 'enforced_by = "lint ruff"\nenforce_when = "ruff-run"\n',
            "rule tmpl.a: enforced_by 'lint ruff' is not <type>:<value>",
        ),
        ('includes = ["nope"]\n' + RULE, "unknown preset 'nope'"),
        ('include_rules = ["basic.nope"]\n' + RULE, "unknown rule 'basic.nope'"),
    ],
)
def test_preset_add_bad_file_gives_one_error_line_and_changes_nothing(repo, capsys, body, message):
    assert main(["init", "--preset", "commits"]) == 0
    path = memdir_of(repo) / "facts" / "default.jsonl"
    before = path.read_bytes()
    preset = repo / "preset.toml"
    if body is not None:
        preset.write_text(body)
    code, out = run(capsys, "preset", "add", "basic", "--file", str(preset))
    assert code == 1
    assert out.count("\n") == 1 and out.startswith(f"error: preset file {preset}: "), out
    assert message in out
    assert path.read_bytes() == before


def test_preset_add_needs_a_name_or_a_file(repo, capsys):
    assert main(["init"]) == 0
    code, out = run(capsys, "preset", "add")
    assert code == 1 and "--file" in out


def test_preset_add_needs_a_memory(repo, capsys):
    code, out = run(capsys, "preset", "add", "basic")
    assert code == 1 and "memory init" in out


def test_hooks_install_still_syncs_guard_on_preset_commit_rule(repo, capsys):
    assert main(["init", "--preset", "dev"]) == 0
    assert main(["hooks", "install", "--agent", "generic", "--commit-msg-guard"]) == 0
    from cairnkit.memory import Memory
    from cairnkit.paths import find_project

    memory = Memory.open(find_project())
    by_key = {s.get("preset_rule"): s for s in memory.states.values()}
    assert by_key["commits.co-author"]["enforced_by"] == "githook:commit-msg"
    assert "enforced_by" not in by_key["dev.git"]


def test_instructions_block_points_to_memory_load_for_preset_rules(repo, capsys):
    assert main(["init", "--preset", "dev"]) == 0
    code, out = run(capsys, "instructions")
    assert code == 0
    assert "Co-authored-by" in out
    assert "`memory load` prints them first" in out
    assert "memory preset list" in out
    assert "Name the command that checks a change" not in out
