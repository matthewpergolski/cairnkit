"""A fact ends with no agent only when the text is the same, byte for byte, in its words.

Whitespace and a final `.`, `,`, `;` or `:` may differ. Any other change goes to the agent task,
and both facts stay active: a repeat costs words, and a false retire loses a fact.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.similar import repeat_key

OLD, NEW = "f-20261001-0001", "f-20261002-0002"
FLAGS = ["--basis", "seen", "--source", "session:2026-11-01"]
ADD_WOULD_END = [
    ("-1 is the limit", "1 is the limit"),
    ("retries != 0", "retries = 0"),
    ("≤ 200 ms", "≥ 200 ms"),
    ("Deploy ✅", "Deploy ❌"),
    ("foo.bar is on", "foo bar is on"),
    ("use --no-cache here", "use no cache here"),
    ("Foo", "foo"),
    ("foo-bar", "foo bar"),
]
TIDY_WOULD_END = [
    ("rails", "rail"),
    ("plan A", "plan"),
    ("table users", "table user"),
    ("cluster A", "cluster"),
    ("GitHub Pages", "GitHub Page"),
    ("a.example.com", "example.com"),
    ("Run step A then step B", "Run step then step B"),
    ("a/b test", "b test"),
    ("Deploys need a clean tree", "deploys need a clean tree"),
    ("The classes pass", "The class passes"),
    ("The release job warms the caches", "Release job warms a cache"),
]
DIFFERENT_WORD = [
    (
        "The staging database lives in us-east-1 and uses replica set alpha for all reads",
        "The production database lives in us-east-1 and uses replica set alpha for all reads",
    ),
    (
        "Payments retry three times before the job gives up and alerts on call",
        "Payments retry five times before the job gives up and alerts on call",
    ),
    ("Use https for the billing API here", "Use http for the billing API here"),
    ("The parser module is written in C++", "The parser module is written in C#"),
    ("Connect to 東京 before the deploy", "Connect to 大阪 before the deploy"),
    ("Service alpha calls service beta at startup", "Service beta calls service alpha at startup"),
    ("The limit x < 5 holds in the loader", "The limit x > 5 holds in the loader"),
    ("Retry 3 times at the gateway", "Retry 4 times at the gateway"),
    ("Tests must not run in the release job", "Tests must run in the release job"),
]
SAME = [
    ("Deploys need a clean tree", "Deploys need a clean tree"),
    ("Deploys need a clean tree", "  Deploys  need\ta clean\ntree  "),
    ("Deploys need a clean tree", "Deploys need a clean tree."),
    ("Deploys need a clean tree;", "Deploys need a clean tree:"),
    ("Deploys need a clean tree .", "Deploys need a clean tree"),
]
NOT_SAME = [
    ("Is it on", "Is it on?"),
    ("println", "println!"),
    ("café", "café"),
    (".", ","),
]


def _ask(capsys, *command):
    capsys.readouterr()
    code = main(list(command))
    return code, capsys.readouterr().out


def _status(fid):
    return Memory.open(find_project(), None).states[fid]["status"]


def _pair(mem, a, b, **older):
    write_facts(
        mem,
        [
            make_fact(OLD, a, learned_at="2026-10-01T00:00:00+00:00", **older),
            make_fact(NEW, b, learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )


@pytest.mark.parametrize("a,b", ADD_WOULD_END)
def test_add_keeps_both_facts_when_any_character_differs(mem, capsys, a, b):
    write_facts(mem, [make_fact(OLD, a)])
    code, out = _ask(capsys, "add", b, *FLAGS)
    assert code == 0 and "has the same words" not in out
    assert _status(OLD) == "active"


@pytest.mark.parametrize("a,b", ADD_WOULD_END + TIDY_WOULD_END + DIFFERENT_WORD)
def test_auto_tidy_keeps_both_facts_and_the_agent_task_lists_the_pair(mem, capsys, a, b):
    _pair(mem, a, b)
    code, out = _ask(capsys, "tidy", "--auto")
    assert code == 0 and "Nothing to retire." in out
    assert _status(OLD) == _status(NEW) == "active"


@pytest.mark.parametrize("a,b", ADD_WOULD_END + TIDY_WOULD_END)
def test_a_change_in_form_reaches_the_agent_task(mem, capsys, a, b):
    _pair(mem, a, b)
    _ask(capsys, "tidy")
    task = (mem / "proposals" / "tidy-followups.md").read_text()
    assert OLD in task and NEW in task


@pytest.mark.parametrize("a,b", SAME)
def test_the_same_text_is_retired(mem, capsys, a, b):
    _pair(mem, a, b)
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "superseded"
    assert _status(NEW) == "active"


@pytest.mark.parametrize("a,b", SAME)
def test_add_supersedes_the_same_text(mem, capsys, a, b):
    write_facts(mem, [make_fact(OLD, a)])
    _, out = _ask(capsys, "add", b, *FLAGS)
    assert "has the same words" in out
    assert _status(OLD) == "superseded"


@pytest.mark.parametrize("a,b", NOT_SAME)
def test_a_mark_that_can_change_the_meaning_keeps_both_facts(mem, capsys, a, b):
    assert repeat_key(a) != repeat_key(b)
    _pair(mem, a, b)
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "active"


def test_a_symbol_only_repeat_is_still_a_repeat(mem, capsys):
    write_facts(mem, [make_fact(OLD, "✅")])
    _, out = _ask(capsys, "add", "✅", *FLAGS)
    assert "has the same words" in out
    assert _status(OLD) == "superseded"


def test_a_rule_repeat_writes_nothing_and_a_rule_in_other_case_is_a_new_rule(mem, capsys):
    write_facts(mem, [make_fact(OLD, "Never force push", kind="rule", basis="told")])
    code, out = _ask(capsys, "add", "Never force push.", "--kind", "rule", *FLAGS)
    assert code == 0 and "already exists" in out
    code, out = _ask(capsys, "add", "never force push", "--kind", "rule", *FLAGS)
    assert code == 0 and "added" in out
    assert _status(OLD) == "active"


def test_the_labelled_set_has_no_false_retire():
    fixture = Path(__file__).parent.parent / "benchmarks" / "fixtures" / "near_repeats.jsonl"
    rows = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
    retired = [row for row in rows if repeat_key(row["a"]) == repeat_key(row["b"])]
    assert retired, "the set must hold a repeat that differs only in whitespace or a final mark"
    assert [row["a"] for row in retired if row["label"] == "different"] == []


def test_add_says_both_stay_for_a_similar_fact(mem, capsys):
    a, b = DIFFERENT_WORD[0]
    write_facts(mem, [make_fact(OLD, a)])
    _, out = _ask(capsys, "add", b, *FLAGS)
    assert "auto-tidy can supersede" not in out
    assert "Both stay active" in out and "agent task" in out
    assert _status(OLD) == "active"


def test_a_stated_fact_is_not_retired_by_a_fact_with_another_basis(mem, capsys):
    _pair(mem, "Deploys need a clean tree", "Deploys need a clean tree", basis="told")
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "active"


def test_a_stated_fact_is_retired_by_the_same_stated_text(mem, capsys):
    text = "Deploys need a clean tree"
    write_facts(
        mem,
        [
            make_fact(OLD, text, basis="told", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(NEW, text, basis="told", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "superseded"


def test_notes_for_two_branches_stay_apart(mem, capsys):
    text = "Deploys need a clean tree"
    write_facts(
        mem,
        [
            make_fact(
                OLD,
                text,
                scope="short",
                until_branch_merged="alpha",
                expires_at="2099-01-01",
                learned_at="2026-10-01T00:00:00+00:00",
            ),
            make_fact(
                NEW,
                text,
                scope="short",
                until_branch_merged="beta",
                expires_at="2099-01-01",
                learned_at="2026-10-02T00:00:00+00:00",
            ),
        ],
    )
    _, out = _ask(capsys, "tidy", "--auto", "--dry-run")
    assert "duplicate" not in out
