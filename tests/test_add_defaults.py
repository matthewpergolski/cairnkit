"""`memory add` needs only the text. The defaults must claim nothing false."""

from __future__ import annotations

import pytest
from conftest import make_fact, write_facts

from cairnkit import autotidy
from cairnkit.cli import main
from cairnkit.clock import parse_time
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.selection import score_parts

NOW = "2026-10-20T12:00:00+00:00"
OLD, NEW = "f-20261001-0001", "f-20261002-0002"


def _memory():
    return Memory.open(find_project(), None)


def _add(capsys, *args):
    capsys.readouterr()
    assert main(["add", *args]) == 0
    out = capsys.readouterr().out
    return out.split("added ")[1].split()[0], out


def test_add_with_only_text_writes_a_guess_from_this_session(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    fact, out = _add(capsys, "The queue drops jobs on restart.")
    state = _memory().fact(fact)
    assert state["basis"] == "guess"
    assert state["source"] == "session:2026-10-20"
    assert "basis guess" in out and "--basis seen" in out


def test_a_stated_basis_and_source_give_no_note(mem, capsys):
    fact, out = _add(capsys, "A fact.", "--basis", "seen", "--source", "commit:abc")
    state = _memory().fact(fact)
    assert (state["basis"], state["source"]) == ("seen", "commit:abc")
    assert "basis guess" not in out


def test_the_default_shows_as_a_guess_in_the_load(mem, capsys):
    fact, _ = _add(capsys, "The queue drops jobs on restart.")
    assert main(["load", "--budget", "0"]) == 0
    line = next(ln for ln in capsys.readouterr().out.splitlines() if fact in ln)
    assert "guess" in line


def test_basis_does_not_change_the_rank():
    moment = parse_time(NOW)
    guess = make_fact(OLD, "Same.", basis="guess")
    seen = make_fact(OLD, "Same.", basis="seen")
    assert score_parts(guess, moment, set(), set()) == score_parts(seen, moment, set(), set())


def test_an_exact_repeat_with_no_basis_keeps_the_older_claim(mem, capsys):
    _add(capsys, "The queue drops jobs.", "--basis", "seen", "--source", "commit:abc")
    fact, out = _add(capsys, "The queue drops jobs.")
    assert _memory().fact(fact)["basis"] == "seen"
    assert "basis guess" not in out


def test_an_exact_repeat_with_a_stated_basis_uses_that_basis(mem, capsys):
    _add(capsys, "The queue drops jobs.", "--basis", "seen", "--source", "commit:abc")
    fact, _ = _add(capsys, "The queue drops jobs.", "--basis", "guess")
    assert _memory().fact(fact)["basis"] == "guess"


def test_a_default_does_not_replace_what_a_person_said(mem, capsys):
    told, _ = _add(capsys, "Ship on Fridays.", "--basis", "told", "--source", "person:owner")
    fact, out = _add(capsys, "Ship on Fridays.")
    assert _memory().fact(told)["status"] == "active"
    assert _memory().fact(fact)["basis"] == "guess"
    assert "not superseded" in out


def test_auto_tidy_does_not_let_a_near_repeat_guess_retire_a_seen_fact(mem, capsys):
    words = "the deploy script needs a clean tree before each staging release run"
    write_facts(
        mem,
        [
            make_fact(OLD, words, basis="seen", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(NEW, words + "s", basis="guess", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    assert autotidy.find(_memory()) == []


def test_auto_tidy_leaves_a_near_repeat_for_the_agent(mem, capsys):
    words = "the deploy script needs a clean tree before each staging release run"
    write_facts(
        mem,
        [
            make_fact(OLD, words, basis="guess", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(NEW, words + "s", basis="seen", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    assert autotidy.find(_memory()) == []


def test_instructions_and_help_name_the_defaults(capsys):
    from cairnkit import instructions

    assert "defaults to `guess`" in instructions.text()
    assert "session:" in instructions.text()
    with pytest.raises(SystemExit):
        main(["add", "--help"])
    out = capsys.readouterr().out
    assert "default: guess" in " ".join(out.split())
    assert "default: session:" in " ".join(out.split())


def test_held_by_alone_says_what_it_needs(mem, repo, capsys):
    fact, _ = _add(capsys, "A rule file holds this.")
    capsys.readouterr()
    assert main(["change", fact, "--held-by", "README.md", "--reason", "moved"]) == 1
    err = capsys.readouterr().err
    assert "--held-by needs --status promoted" in err
    assert f"memory change {fact} --status promoted --held-by README.md" in err
