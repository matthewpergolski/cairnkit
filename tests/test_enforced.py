"""Rule tiers: a rule with `enforced_by` names the check that fails when it is broken."""

from conftest import git, make_fact, read_jsonl, write_facts

from cairnkit.cli import main
from cairnkit.rules import DEFAULT_RULES

RULE = ["--kind", "rule", "--area", "git", "--basis", "told", "--source", "person:owner"]


def add(capsys, text, *extra):
    capsys.readouterr()
    code = main(["add", text, *extra])
    out = capsys.readouterr().out.strip()
    return code, out.split()[-1] if code == 0 else None


def test_add_enforced_rule(mem, capsys):
    code, fid = add(capsys, "No print calls.", *RULE, "--enforced-by", "lint:ruff:T201")
    assert code == 0
    [rec] = read_jsonl(mem / "facts" / "main.jsonl")
    assert rec["id"] == fid and rec["enforced_by"] == "lint:ruff:T201"


def test_enforced_by_format_is_checked(mem, capsys):
    for bad in ("ruff", "lint: ruff", "Lint:ruff", "lint:"):
        assert add(capsys, "A rule.", *RULE, "--enforced-by", bad)[0] == 1, bad
    assert not (mem / "facts" / "main.jsonl").exists()


def test_enforced_by_only_on_rules(mem, capsys):
    trap = ["--kind", "trap", "--area", "x", "--basis", "seen", "--source", "commit:abc"]
    assert add(capsys, "A trap.", *trap, "--enforced-by", "test:tests/test_x.py")[0] == 1
    _, tid = add(capsys, "A trap.", *trap)
    assert main(["change", tid, "--enforced-by", "test:tests/test_x.py"]) == 1


def test_change_sets_and_clears_append_only(mem, capsys):
    _, fid = add(capsys, "Run the tests.", *RULE)
    path = mem / "facts" / "main.jsonl"
    before = path.read_bytes()
    assert main(["change", fid, "--enforced-by", "ci:tests"]) == 0
    assert path.read_bytes().startswith(before)
    assert read_jsonl(path)[-1]["enforced_by"] == "ci:tests"
    capsys.readouterr()
    main(["load"])
    out = capsys.readouterr().out
    assert out.index("## Enforced rules") < out.index("Run the tests.")
    assert "enforced by ci:tests" in out
    assert main(["change", fid, "--no-enforced-by", "--reason", "CI job removed."]) == 0
    assert read_jsonl(path)[-1]["enforced_by"] is None
    capsys.readouterr()
    main(["load"])
    out = capsys.readouterr().out
    assert "## Enforced rules" not in out
    assert out.index("## Advisory rules") < out.index("Run the tests.")
    assert main(["check", "--strict"]) == 0


def test_load_groups_rules_outside_the_budget(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Enforced one.", kind="rule", enforced_by="ci:lint"),
            make_fact("f-20261001-0002", "Advisory one.", kind="rule"),
            make_fact("f-20261001-0003", "A plain fact."),
        ],
    )
    capsys.readouterr()
    main(["load", "--budget", "1"])
    out = capsys.readouterr().out
    order = [
        "## Enforced rules (a check fails if broken)",
        "Enforced one.",
        "## Advisory rules",
        "Advisory one.",
        "## Long-term",
    ]
    assert [out.index(s) for s in order] == sorted(out.index(s) for s in order)


def test_check_reports_bad_enforced_by(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Bad format.", kind="rule", enforced_by="no colon"),
            make_fact("f-20261001-0002", "Not a rule.", kind="trap", enforced_by="ci:x"),
            make_fact("f-20261001-0003", "A fact."),
            {
                "type": "change",
                "id": "f-20261001-0003",
                "at": "2026-10-02T12:00:00+00:00",
                "enforced_by": "ci:x",
                "writer": "main",
            },
        ],
    )
    capsys.readouterr()
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert out.count("enforced_by") >= 3


def test_check_advisory_lists_prose_rules(mem, capsys):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Enforced one.", kind="rule", enforced_by="ci:lint"),
            make_fact("f-20261001-0002", "Advisory one.", kind="rule"),
        ],
    )
    capsys.readouterr()
    assert main(["check", "--advisory"]) == 0
    out = capsys.readouterr().out
    assert "Advisory one." in out and "f-20261001-0002" in out
    assert "Enforced one." not in out
    capsys.readouterr()
    main(["check"])
    assert "Advisory one." not in capsys.readouterr().out


def _defaults(repo):
    records = read_jsonl(repo.parent / "proj.memory" / "facts" / "default.jsonl")
    return {r["text"]: r for r in records if r["type"] == "fact"}


def _load(capsys):
    capsys.readouterr()
    main(["load", "--budget", "0"])
    return capsys.readouterr().out


def test_init_without_guard_seeds_advisory_rules(repo, capsys):
    assert main(["init", "--preset", "commits"]) == 0
    assert all("enforced_by" not in r for r in _defaults(repo).values())
    assert "## Enforced rules" not in _load(capsys)


def test_init_after_local_guard_seeds_an_enforced_rule(repo, capsys):
    assert main(["hooks", "install", "--agent", "generic", "--commit-msg-guard"]) == 0
    assert main(["init", "--preset", "commits"]) == 0
    rules = _defaults(repo)
    assert rules[DEFAULT_RULES[0]]["enforced_by"] == "githook:commit-msg"
    assert "enforced_by" not in rules[DEFAULT_RULES[2]]


def test_guard_install_and_uninstall_update_the_default_rule(repo, capsys):
    assert main(["init", "--preset", "commits"]) == 0
    assert main(["hooks", "install", "--agent", "generic", "--commit-msg-guard"]) == 0
    out = _load(capsys)
    enforced = out[out.index("## Enforced rules") : out.index("## Advisory rules")]
    assert "Co-authored-by" in enforced
    assert main(["hooks", "install", "--agent", "generic", "--commit-msg-guard"]) == 0
    assert _load(capsys) == out  # no second change record changes nothing
    assert main(["check", "--strict"]) == 0
    assert main(["hooks", "uninstall"]) == 0
    assert "## Enforced rules" not in _load(capsys)


def test_shared_guard_counts_only_when_hooks_path_is_set(repo, capsys):
    assert main(["init", "--preset", "commits"]) == 0
    assert main(["hooks", "install", "--agent", "generic", "--commit-msg-guard=shared"]) == 0
    assert "## Enforced rules" not in _load(capsys)
    git(repo, "config", "core.hooksPath", ".githooks")
    assert main(["hooks", "install", "--agent", "generic", "--commit-msg-guard=shared"]) == 0
    assert "## Enforced rules" in _load(capsys)


def test_show_prints_enforced_by_and_its_history(mem, capsys):
    _, fid = add(capsys, "Run the tests.", *RULE, "--enforced-by", "ci:tests")
    assert main(["change", fid, "--no-enforced-by", "--reason", "Job removed."]) == 0
    assert main(["change", fid, "--enforced-by", "ci:unit"]) == 0
    capsys.readouterr()
    main(["show", fid])
    out = capsys.readouterr().out
    assert "enforced_by: ci:unit" in out
    assert "advisory: Job removed." in out and "enforced by ci:unit" in out
