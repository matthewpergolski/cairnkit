"""Rules sit outside the word budget of `memory load`. `memory check` notes a long rule set."""

from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.hookrun import _cut
from cairnkit.selection import APPROVAL_RULES, FRAME_FOOTER, FRAME_HEADER

LONG_RULE = (
    "Follow this long rule about the way that work is done in this project, every day, "
    "for each change, with care, in each part of the code and the docs."
)


def rules(count: int) -> list[dict]:
    return [
        make_fact(f"f-20261001-{i:04x}", f"{LONG_RULE} Number {i}.", kind="rule")
        for i in range(1, count + 1)
    ]


def test_load_rules_do_not_use_word_budget(mem, capsys):
    decision = make_fact(
        "f-20261002-0001",
        "Search is done. The next phase is answer evaluation, and it starts with a plan.",
        kind="decision",
    )
    write_facts(mem, [*rules(10), decision])
    capsys.readouterr()
    assert main(["load", "--budget", "200"]) == 0
    out = capsys.readouterr().out
    assert out.count("Follow this long rule") == 10
    assert "Search is done." in out


def test_check_notes_when_rules_exceed_word_cap(mem, capsys):
    write_facts(mem, rules(20))
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "note: 20 active rule(s) hold" in out
    assert "words" in out


def test_check_is_quiet_about_a_short_rule_set(mem, capsys):
    write_facts(mem, rules(3))
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "note:" not in capsys.readouterr().out


def approvals(count: int) -> list[dict]:
    return [
        make_fact(f"f-20261003-{i:04x}", f"Yes to the parser rewrite, part {i}.", kind="rule")
        for i in range(1, count + 1)
    ]


def lines_of_load(capsys, budget: str) -> list[str]:
    capsys.readouterr()
    assert main(["load", "--budget", budget]) == 0
    return capsys.readouterr().out.splitlines()


def test_one_time_approvals_bind_below_the_lasting_rules(mem, capsys):
    lasting = make_fact("f-20261002-0002", "Never force-push to main.", kind="rule")
    write_facts(mem, [*approvals(9), lasting])
    lines = lines_of_load(capsys, "40")
    assert not any("outside the word budget" in line for line in lines)
    heading = lines.index(APPROVAL_RULES)
    shown = [n for n, line in enumerate(lines) if "Yes to the parser rewrite" in line]
    assert len(shown) == 9
    assert lines.index("## Advisory rules") < heading < min(shown)
    assert max(shown) < lines.index(FRAME_HEADER), "an approval of the owner still binds"


def test_one_time_approvals_use_the_word_budget_of_the_facts(mem, capsys):
    decision = make_fact("f-20261002-0001", "Search is done; answer evaluation is next.")
    write_facts(mem, [decision])
    assert any("Search is done" in line for line in lines_of_load(capsys, "60"))
    write_facts(mem, approvals(9))
    assert not any("Search is done" in line for line in lines_of_load(capsys, "60"))


def test_check_does_not_count_approvals_as_lasting_rules(mem, capsys):
    write_facts(mem, approvals(80))
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "active rule(s) hold" not in capsys.readouterr().out


def test_a_cut_hook_load_keeps_the_approvals():
    lines = [
        "# Project memory (/m)",
        APPROVAL_RULES,
        "- [f-20261003-0001] Yes to the parser rewrite.",
        FRAME_HEADER,
        "## Long-term",
        "- [f-20261001-0001] " + "x" * 300,
        FRAME_FOOTER,
        "2 fact(s) shown.",
    ]
    out = _cut("\n".join(lines), 200)
    assert "Yes to the parser rewrite." in out and "x" * 300 not in out
