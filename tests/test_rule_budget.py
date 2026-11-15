"""Rules sit outside the word budget of `memory load`. `memory check` notes a long rule set."""

import io
import json

from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.hookrun import HOOK_TEXT_LIMIT, _cut
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


def approvals(count: int, words: str = "") -> list[dict]:
    return [
        make_fact(
            f"f-20261003-{i:04x}", f"Yes to the parser rewrite, part {i}.{words}", kind="rule"
        )
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


PLAN = (
    " Move the tokenizer into its own module, keep the public API stable, add tests for each "
    "token kind, and update the docs page for the parser in the same pull request."
)


def test_a_pile_of_approvals_is_held_back_first_and_the_hook_text_fits(mem, capsys, monkeypatch):
    """The field case: 60 approvals gave a session start text of 15,358 characters."""
    lasting = [
        make_fact(f"f-20261002-{i:04x}", f"Lasting rule {i}: {LONG_RULE}", kind="rule")
        for i in range(1, 6)
    ]
    write_facts(mem, [*lasting, *approvals(60, PLAN)])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    text = capsys.readouterr().out
    assert len(text) <= HOOK_TEXT_LIMIT
    assert all(f"Lasting rule {i}:" in text for i in range(1, 6))
    held = next(line for line in text.splitlines() if "held back" in line)
    assert "f-20261003-" in held and "f-20261002" not in held


def test_a_misread_lasting_rule_binds_under_a_heading_that_claims_no_end(mem, capsys):
    rule = make_fact("f-20261002-0003", "Merge only after the owner approves the PR.", kind="rule")
    write_facts(mem, [rule])
    lines = lines_of_load(capsys, "600")
    at = next(n for n, line in enumerate(lines) if "Merge only after" in line)
    heading = next(line for line in reversed(lines[:at]) if line.startswith("## "))
    assert heading == APPROVAL_RULES
    assert "they bind" in heading and "when the work of one is done" in heading
    assert "One-time" not in heading and at < lines.index(FRAME_HEADER)


def test_an_enforced_rule_stays_with_the_lasting_rules(mem, capsys):
    checked = make_fact(
        "f-20261002-0004",
        "Merge only after the owner approves the PR.",
        kind="rule",
        enforced_by="test:tests/test_merge.py",
    )
    write_facts(mem, [checked])
    lines = lines_of_load(capsys, "600")
    assert APPROVAL_RULES not in lines
    at = next(n for n, line in enumerate(lines) if "Merge only after" in line)
    assert lines[at - 1] == "## Advisory rules"
    assert "(no check found for test:tests/test_merge.py)" in lines[at]


def test_check_does_not_count_approvals_as_lasting_rules(mem, capsys):
    write_facts(mem, approvals(80))
    capsys.readouterr()
    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert "active rule(s) hold" not in out
    assert "note: 80 rule(s) that may be for one piece of work hold 560 more words" in out


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


def todo_line(capsys, words: str) -> str:
    capsys.readouterr()
    assert main(["load"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("memory check:") and " to do " in line for line in lines)
    return next(line for line in lines if words in line)


def test_the_load_names_the_one_time_rules_that_are_over_the_cap(mem, capsys):
    """The field case: a load said "1 to do", and the agent could not tell which facts."""
    write_facts(mem, approvals(80))
    line = todo_line(capsys, "may be for one piece of work")
    named = ", ".join(f"f-20261003-{i:04x}" for i in range(1, 6))
    assert f"hold 560 more words: {named} and 75 more." in line
    assert "f-20261003-0006" not in line
    assert "`memory load --budget 0` lists all" in line


def test_the_load_names_the_longest_lasting_rules_when_they_are_over_the_cap(mem, capsys):
    longest = make_fact("f-20261001-00ff", f"{LONG_RULE} {LONG_RULE}", kind="rule")
    write_facts(mem, [*rules(20), longest])
    line = todo_line(capsys, "active rule(s) hold")
    assert "The longest: f-20261001-00ff, f-20261001-0001, f-20261001-0002," in line
    assert "f-20261001-0004 and 16 more." in line
    assert "`memory load --budget 0` lists all" in line
