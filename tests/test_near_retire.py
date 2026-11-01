"""Auto-tidy retires a near repeat only when no differing word can change the meaning."""

from __future__ import annotations

import pytest
from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.similar import exact_key, near_key

OLD, NEW = "f-20261001-0001", "f-20261002-0002"
DIFFERENT = [
    (
        "The staging database lives in us-east-1 and uses replica set alpha for all reads",
        "The production database lives in us-east-1 and uses replica set alpha for all reads",
    ),
    (
        "Payments retry three times before the job gives up and alerts on call",
        "Payments retry five times before the job gives up and alerts on call",
    ),
    ("Use https for the billing API here", "Use http for the billing API here"),
    ("Runs only on Windows after the build", "Runs only on window after the build"),
    ("The news feed loads from the cache", "The new feed loads from the cache"),
    ("The parser module is written in C++", "The parser module is written in C#"),
    ("Connect to 東京 before the deploy", "Connect to 大阪 before the deploy"),
    ("Service alpha calls service beta at startup", "Service beta calls service alpha at startup"),
    ("Merge the branch then run the tests", "Run the tests then merge the branch"),
    ("The limit x < 5 holds in the loader", "The limit x > 5 holds in the loader"),
    ("The old job was broken in the release", "The old job is broken in the release"),
    ("The cache must be warmed before the job runs", "The cache must be warmed before the job now"),
    ("A push does not count as a session start", "A push or a merge does not count"),
    ("Deploys read the config file on the host", "Deploys read this config file on the host"),
    ("Retry 3 times at the gateway", "Retry 4 times at the gateway"),
    ("Tests must not run in the release job", "Tests must run in the release job"),
    ("Keep the session token out of the logs", "Keep the session token out of the log files"),
]
TRIVIAL = [
    ("Deploys need a clean tree.", "deploys need a CLEAN tree!"),
    ("Deploys need a clean tree", "Deploy needs a clean tree"),
    ("The release job warms the caches", "Release jobs warms a cache"),
    ("The cache is cold after a deploy", "Cache are cold after the deploy"),
    ("Branches retries the batches", "Branch retry the batch"),
    ("The `foo_bar` module (see docs)", "the foo bar module - see docs"),
    ("The classes pass", "The class passes"),
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


@pytest.mark.parametrize("a,b", DIFFERENT)
def test_a_pair_with_a_differing_word_is_not_retired(mem, capsys, a, b):
    _pair(mem, a, b)
    code, out = _ask(capsys, "tidy", "--auto")
    assert code == 0 and "Nothing to retire." in out
    assert _status(OLD) == "active"


@pytest.mark.parametrize("a,b", TRIVIAL)
def test_a_trivial_form_change_is_retired(mem, capsys, a, b):
    _pair(mem, a, b)
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "superseded"
    assert _status(NEW) == "active"


def test_each_key_keeps_order_and_needs_words():
    assert exact_key("alpha calls beta") != exact_key("beta calls alpha")
    assert near_key("alpha calls beta") != near_key("beta calls alpha")
    assert near_key("The") == ()


def test_a_flagged_pair_goes_to_the_agent_task(mem, capsys):
    _pair(mem, *DIFFERENT[0])
    _ask(capsys, "tidy")
    task = (mem / "proposals" / "tidy-followups.md").read_text()
    assert OLD in task and NEW in task


@pytest.mark.parametrize(
    "a,b",
    [
        ("Service alpha calls service beta at startup", "Service beta calls service alpha at startup"),
        ("The parser module is written in C++", "The parser module is written in C#"),
    ],
)
def test_add_does_not_supersede_when_the_same_words_say_something_else(mem, capsys, a, b):
    write_facts(mem, [make_fact(OLD, a)])
    code, out = _ask(capsys, "add", b, "--basis", "seen", "--source", "session:2026-11-01")
    assert code == 0 and "superseded" not in out.split("similar to")[0]
    assert _status(OLD) == "active"


def test_add_says_auto_tidy_leaves_a_pair_with_a_differing_word(mem, capsys):
    a, b = DIFFERENT[0]
    write_facts(mem, [make_fact(OLD, a)])
    _, out = _ask(capsys, "add", b, "--basis", "seen", "--source", "session:2026-11-01")
    assert "auto-tidy can supersede" not in out
    assert "agent task" in out


def test_add_says_auto_tidy_can_retire_a_trivial_change(mem, capsys):
    a = "The cache must be warmed before the release job runs in staging"
    b = "The cache must be warmed before the release jobs runs in staging"
    write_facts(mem, [make_fact(OLD, a)])
    _, out = _ask(capsys, "add", b, "--basis", "seen", "--source", "session:2026-11-01")
    assert "auto-tidy can supersede" in out


@pytest.mark.parametrize("a,b", TRIVIAL[:3])
def test_a_stated_fact_is_not_retired_by_a_fact_with_another_basis(mem, capsys, a, b):
    _pair(mem, a, b, basis="told")
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "active"


def test_a_stated_fact_is_retired_only_by_a_stated_trivial_change(mem, capsys):
    a, b = TRIVIAL[2]
    write_facts(
        mem,
        [
            make_fact(OLD, a, basis="told", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(NEW, b, basis="told", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "superseded"


def test_two_stated_facts_with_a_differing_word_both_stay(mem, capsys):
    a = "The staging cluster has four nodes and runs in region east"
    b = "The staging cluster has six nodes and runs in region east"
    write_facts(
        mem,
        [
            make_fact(OLD, a, basis="told", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(NEW, b, basis="told", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "active"


def test_a_stated_newer_fact_does_not_retire_a_different_older_fact(mem, capsys):
    a, b = DIFFERENT[0]
    write_facts(
        mem,
        [
            make_fact(OLD, a, learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(NEW, b, basis="told", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "active"


def test_a_guess_does_not_retire_an_observation_on_a_trivial_change(mem, capsys):
    a, b = TRIVIAL[2]
    write_facts(
        mem,
        [
            make_fact(OLD, a, basis="seen", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(NEW, b, basis="guess", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    _ask(capsys, "tidy", "--auto")
    assert _status(OLD) == "active"


def test_notes_for_two_branches_stay_apart(mem, capsys):
    a, b = TRIVIAL[2]
    write_facts(
        mem,
        [
            make_fact(
                OLD,
                a,
                scope="short",
                until_branch_merged="alpha",
                learned_at="2026-10-01T00:00:00+00:00",
            ),
            make_fact(
                NEW,
                b,
                scope="short",
                until_branch_merged="beta",
                learned_at="2026-10-02T00:00:00+00:00",
            ),
        ],
    )
    _, out = _ask(capsys, "tidy", "--auto", "--dry-run")
    assert OLD not in out.split("Kept")[0] or "Would retire" not in out
