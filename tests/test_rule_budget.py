"""Rules sit outside the word budget of `memory load`. `memory check` notes a long rule set."""

from conftest import make_fact, write_facts

from cairnkit.cli import main

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
