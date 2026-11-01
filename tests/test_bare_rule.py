"""A rule an agent saves with no basis loads as data. The agent hears this at once, with the fix."""

from __future__ import annotations

import os
import re
import subprocess
import sys

from conftest import git, make_fact, write_facts

from cairnkit.cli import main
from cairnkit.instructions import text as instruction_text
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.selection import AGENT_RULES, FRAME_HEADER, RULE_WORD_LIMIT

RULE = "Never run the migration on a Friday."
BARE = ["add", RULE, "--kind", "rule"]
TOLD = [*BARE, "--basis", "told"]
SHORT_LINE = 30
SHORT_HEADING = 16


def _add(capsys, argv: list[str]) -> list[str]:
    capsys.readouterr()
    assert main(argv) == 0
    return capsys.readouterr().out.splitlines()


def _load(capsys) -> tuple[str, str]:
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    return out.split(FRAME_HEADER)[0], out


def _active(text: str) -> list[dict]:
    states = Memory.open(find_project(), None).states.values()
    return [s for s in states if s["status"] == "active" and s["text"] == text]


def test_the_first_line_says_it_loads_as_data_and_how_to_lift_it(mem, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    lines = _add(capsys, BARE)
    assert "loads as data" in lines[0]
    assert "same command with --basis told" in lines[0]
    assert "owner stated" in lines[0]
    assert len(lines[0].split()) <= SHORT_LINE
    assert [line for line in lines if "basis guess" in line] == []
    assert lines[-1].startswith("added f-")


def test_the_rule_is_written_and_loads_under_a_heading_that_names_the_lift(
    mem, capsys, monkeypatch
):
    monkeypatch.setenv("CLAUDECODE", "1")
    _add(capsys, BARE)
    above, whole = _load(capsys)
    assert RULE not in above
    heading = next(line for line in whole.splitlines() if line.startswith("## Rules an agent"))
    assert heading == AGENT_RULES
    assert whole.index(FRAME_HEADER) < whole.index(heading) < whole.index(RULE)
    assert "--basis told" in heading
    assert len(heading.split()) <= SHORT_HEADING


def test_the_same_command_with_told_lifts_the_rule(mem, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    first = _add(capsys, BARE)
    old = re.search(r"f-\d+-[0-9a-f]+", first[-1])[0]
    lines = _add(capsys, TOLD)
    assert not any("loads as data" in line for line in lines)
    assert any(f"superseded {old}" in line for line in lines)
    above, whole = _load(capsys)
    assert RULE in above
    assert AGENT_RULES not in whole
    assert [state["basis"] for state in _active(RULE)] == ["told"]


def test_a_bare_repeat_names_the_lift_and_writes_nothing(mem, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    _add(capsys, BARE)
    lines = _add(capsys, BARE)
    assert lines[0].startswith("already exists")
    assert "--basis told" in lines[0]
    assert len(_active(RULE)) == 1


def test_a_person_gets_no_data_note(mem, capsys, monkeypatch):
    for name in ("CLAUDECODE", "CURSOR_AGENT"):
        monkeypatch.delenv(name, raising=False)
    lines = _add(capsys, BARE)
    assert not any("loads as data" in line for line in lines)
    assert RULE in _load(capsys)[0]


def test_the_instructions_show_the_rule_of_an_owner_with_told():
    words = " ".join(instruction_text().split())
    assert '`memory add "TEXT" --kind rule --basis told`' in words


def test_parallel_bare_and_told_adds_leave_one_lifted_rule(mem, repo):
    env = {**os.environ, "CLAUDECODE": "1"}
    adders = [
        subprocess.Popen(
            [sys.executable, "-m", "cairnkit", *argv],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for argv in [BARE, TOLD] * 4
    ]
    for adder in adders:
        _, err = adder.communicate(timeout=60)
        assert adder.returncode == 0, err
    assert [state["basis"] for state in _active(RULE)] == ["told"]


def _pile_of_owner_rules(mem) -> int:
    count = RULE_WORD_LIMIT // 20
    write_facts(
        mem,
        [
            make_fact(
                f"f-20261001-{index:04x}",
                f"Rule{index} " + "word " * 40,
                kind="rule",
                basis="told",
            )
            for index in range(count)
        ],
    )
    return count


def test_an_owner_rule_past_the_bound_is_named_in_a_warning(mem, capsys):
    count = _pile_of_owner_rules(mem)
    _, whole = _load(capsys)
    shown = sum(line.startswith("- [f-") for line in whole.splitlines())
    held = count - shown
    assert held > 0
    assert f"warning: {held} rule(s) held back" in whole


def test_a_rule_against_ai_attribution_past_the_bound_installs_the_guard(mem, repo, capsys):
    _pile_of_owner_rules(mem)
    rule = "No AI attribution in commits or pull requests."
    write_facts(
        mem,
        [
            make_fact(
                "f-20261102-0001",
                rule,
                kind="rule",
                basis="told",
                learned_at="2026-11-02T00:00:00+00:00",
            )
        ],
    )
    _, whole = _load(capsys)
    assert rule not in whole, "this rule must be one that the bound held back"
    assert main(["hooks", "install"]) == 0
    git(repo, "config", "user.name", "x")
    (repo / "x").write_text("x")
    git(repo, "add", "x")
    refused = subprocess.run(
        ["git", "commit", "-q", "-m", "x\n\nCo-authored-by: Claude <noreply@anthropic.com>"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert refused.returncode != 0
    assert "AI attribution" in refused.stderr
