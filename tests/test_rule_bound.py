"""The rule word limit: an instruction outranks data, and a held rule is named."""

from __future__ import annotations

import json
import random

from cairnkit.cli import main
from cairnkit.selection import RULE_WORD_LIMIT, bound_rules, owner_rule, render, words_in

FILL = " ".join(["word"] * 80)


def rule(index: int, text: str = FILL, day: int = 1, **extra) -> dict:
    return {
        "id": f"f-202610{day:02d}-{index:04x}",
        "kind": "rule",
        "text": text,
        "area": "general",
        "happened_at": f"2026-10-{day:02d}",
        "learned_at": f"2026-10-{day:02d}T10:00:00+00:00",
        "source": "session:1",
        "basis": "seen",
        "status": "active",
        "scope": "long",
        "writer": "me",
        **extra,
    }


def ids(rules: list[dict]) -> list[str]:
    return [state["id"] for state in rules]


def plant(mem, rules: list[dict]) -> None:
    lines = [json.dumps({"type": "fact", **state}) for state in rules]
    (mem / "facts" / "me.jsonl").write_text("\n".join(lines) + "\n")


def pile(start: int = 0, count: int = 20, day: int = 1) -> list[dict]:
    return [rule(start + index, day=day) for index in range(count)]


def test_an_owner_rule_that_does_not_fit_also_holds_a_smaller_agent_rule():
    late = rule(100, " ".join(["late"] * 300), day=20)
    data = rule(101, "small data rule", day=21, author="agent:claude")
    fill = [rule(index, " ".join(["word"] * 95)) for index in range(9)]
    shown, held = bound_rules([*fill, data, late])
    assert owner_rule(late) and not owner_rule(data)
    assert data in held
    assert data not in shown


def test_no_mix_of_rules_holds_an_owner_rule_while_an_agent_rule_prints():
    pick = random.Random(7)
    for _ in range(300):
        rules = []
        for index in range(pick.randint(1, 30)):
            extra = {}
            if pick.random() < 0.5:
                extra["author"] = "agent:claude"
                if pick.random() < 0.3:
                    extra["basis"] = "told"
            if pick.random() < 0.3:
                extra["enforced_by"] = "ci:job"
            size = pick.choice([3, 20, 90, 130, 400, 1200])
            rules.append(rule(index, " ".join(["word"] * size), pick.randint(1, 28), **extra))
        shown, held = bound_rules(rules)
        if any(owner_rule(state) for state in held):
            assert all(owner_rule(state) for state in shown)
        assert sum(words_in(render(state)) for state in shown) <= RULE_WORD_LIMIT


def test_a_later_told_rule_is_not_crowded_out_by_seen_rules():
    late = rule(100, "Told late rule", day=20, basis="told")
    shown, held = bound_rules([*pile(), late])
    assert late in shown
    assert held


def test_the_newest_owner_rule_wins_a_tie():
    older = rule(1, " ".join(["word"] * 900), day=1)
    newer = rule(2, " ".join(["word"] * 900), day=2)
    assert bound_rules([older, newer]) == ([newer], [older])


def test_a_rule_with_a_check_is_the_first_to_be_held_inside_a_class():
    checked = rule(1, " ".join(["word"] * 900), day=2, enforced_by="ci:job")
    plain = rule(2, " ".join(["word"] * 900), day=1)
    assert bound_rules([checked, plain]) == ([plain], [checked])


def test_the_order_does_not_depend_on_the_order_of_the_files():
    same_second = [*pile(), *pile(50, 20, day=2), rule(200, day=2, author="agent:claude")]
    first = bound_rules(same_second)
    for seed in range(5):
        random.Random(seed).shuffle(same_second)
        assert bound_rules(same_second) == first


def test_the_load_prints_the_told_rule_and_holds_the_agent_rule(repo, mem, capsys):
    late = rule(100, "OWNER-LATE " + " ".join(["late"] * 300), day=20, basis="told")
    data = rule(101, "AGENT-DATA small rule", day=21, author="agent:claude")
    fill = [rule(index, " ".join(["word"] * 95)) for index in range(10)]
    plant(mem, [*fill, data, late])
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "OWNER-LATE" in out
    assert "AGENT-DATA" not in out


def test_the_warning_names_up_to_five_ids_and_how_to_read_them_all(repo, mem, capsys):
    rules = pile()
    plant(mem, rules)
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    line = next(row for row in out.splitlines() if "rule(s) held back" in row)
    shown = [state["id"] for state in rules if f"[{state['id']}]" in out]
    named = [state["id"] for state in rules if state["id"] in line]
    assert len(named) == 5
    assert not set(named) & set(shown)
    assert f"and {20 - len(shown) - 5} more" in line
    assert "memory load --budget 0" in line


def test_a_short_list_of_held_rules_names_each_one(repo, mem, capsys):
    rules = [rule(1, " ".join(["word"] * 900), day=1), rule(2, " ".join(["word"] * 900), day=2)]
    plant(mem, rules)
    assert main(["load"]) == 0
    line = next(row for row in capsys.readouterr().out.splitlines() if "held back" in row)
    assert rules[0]["id"] in line
    assert "more" not in line
