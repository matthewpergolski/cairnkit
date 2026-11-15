"""The newest things the owner said reach a new session first.

In a real project the session start showed 16 of 51 facts and held back everything the owner
had said in two days, his two open questions among them. Old facts, one for each of 14 areas,
took the budget first.
"""

from __future__ import annotations

from conftest import make_fact, write_facts

from cairnkit.cli import main

OLD_WORDS = "the deploy keeps its queue drained before a restart so that no job is lost"


def old_facts(count: int) -> list[dict]:
    """Traps of last week, each looked up on purpose, as an agent's searches leave them."""
    return [
        make_fact(
            f"f-20261028-{n:04x}",
            f"Old fact {n}: {OLD_WORDS}.",
            area=f"area{n}",
            kind="trap",
            learned_at="2026-10-28T12:00:00+00:00",
        )
        for n in range(count)
    ]


def look_up(facts: list[dict]) -> None:
    for fact in facts:
        assert main(["show", fact["id"]]) == 0


def told(fid: str, text: str, day: str, area: str = "area0") -> dict:
    """An owner statement in an area that older facts already hold."""
    at = f"{day}T12:00:00+00:00"
    return make_fact(fid, text, basis="told", kind="decision", learned_at=at, area=area)


def load(capsys, budget: int) -> str:
    capsys.readouterr()
    assert main(["load", "--budget", str(budget)]) == 0
    return capsys.readouterr().out


def test_the_owner_s_newest_statements_load_before_old_facts(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", "2026-11-03T12:00:00+00:00")
    question = told(
        "f-20261103-0001",
        "The owner asked whether a prod release fits before Nov 26.",
        "2026-11-03",
    )
    accepted = told("f-20261103-0002", "The owner accepted decision record 0006.", "2026-11-03")
    old = old_facts(14)
    write_facts(mem, [*old, question, accepted])
    look_up(old)
    text = load(capsys, 120)
    assert "prod release fits before Nov 26" in text
    assert "accepted decision record 0006" in text


def test_only_the_newest_few_statements_jump_the_queue(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", "2026-11-03T12:00:00+00:00")
    many = [
        told(
            f"f-20261020-{n:04x}", f"Owner said item {n}.", f"2026-10-{10 + n:02d}", f"area{n % 3}"
        )
        for n in range(12)
    ]
    old = old_facts(3)
    write_facts(mem, [*old, *many])
    look_up(old)
    text = load(capsys, 60)
    assert "Owner said item 11." in text
    assert "Owner said item 0." not in text
