"""Ranked load: under the word budget, rules first, then facts by an explainable score."""

from datetime import timedelta

from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.clock import parse_time
from cairnkit.selection import score_parts

NOW = "2026-10-20T12:00:00+00:00"
OLDER, NEWER = "f-20260901-0001", "f-20260910-0002"


def load(capsys, *args):
    capsys.readouterr()
    assert main(["load", *args]) == 0
    return capsys.readouterr().out


def two_facts(mem):
    write_facts(
        mem,
        [
            make_fact(OLDER, "Older fact here.", learned_at="2026-09-01T00:00:00+00:00"),
            make_fact(NEWER, "Newer fact here.", learned_at="2026-09-10T00:00:00+00:00"),
        ],
    )


def test_without_use_the_newer_fact_wins_the_budget(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    two_facts(mem)
    out = load(capsys, "--budget", "8")
    assert "Newer fact here." in out and "Older fact here." not in out


def test_a_fact_that_was_shown_lately_outranks_a_newer_one(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    two_facts(mem)
    assert main(["show", OLDER]) == 0
    out = load(capsys, "--budget", "8")
    assert "Older fact here." in out and "Newer fact here." not in out


def test_a_search_hit_counts_as_use(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    two_facts(mem)
    assert main(["search", "older"]) == 0
    out = load(capsys, "--budget", "8")
    assert "Older fact here." in out and "Newer fact here." not in out


def test_loading_alone_is_not_use(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    two_facts(mem)
    load(capsys, "--budget", "8")
    load(capsys, "--budget", "8")
    assert not (mem / ".usage").exists()


def test_use_from_two_writers_is_merged(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    two_facts(mem)
    monkeypatch.setenv("MEMORY_WRITER", "other")
    assert main(["show", OLDER]) == 0
    monkeypatch.setenv("MEMORY_WRITER", "main")
    out = load(capsys, "--budget", "8")
    assert "Older fact here." in out


def test_use_fades_with_time():
    state = make_fact(OLDER, "Fact.")
    moment = parse_time(NOW)
    fresh = score_parts(state, moment, set(), set(), moment - timedelta(days=1))["use"]
    stale = score_parts(state, moment, set(), set(), moment - timedelta(days=60))["use"]
    never = score_parts(state, moment, set(), set(), None)["use"]
    assert fresh > stale > never == 0.0
    assert stale < 0.2


def test_a_broken_usage_log_never_breaks_show(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    two_facts(mem)
    (mem / ".usage").write_text("not a folder")
    capsys.readouterr()
    assert main(["show", OLDER]) == 0
    assert "Older fact here." in capsys.readouterr().out
    assert "Older fact here." not in load(capsys, "--budget", "8")


def test_rules_stay_first_and_outside_the_budget(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, [make_fact("f-20261001-0009", "Always run the tests.", kind="rule")])
    two_facts(mem)
    out = load(capsys, "--budget", "8")
    assert out.index("Always run the tests.") < out.index("Newer fact here.")


def test_explain_shows_each_part_of_each_score(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    two_facts(mem)
    assert main(["show", OLDER]) == 0
    out = load(capsys, "--budget", "8", "--explain")
    assert "Ranking" in out
    for part in ("recency", "kind", "area", "branch", "use"):
        assert part in out
    line_older = next(ln for ln in out.splitlines() if ln.startswith(f"- [{OLDER}] total"))
    line_newer = next(ln for ln in out.splitlines() if ln.startswith(f"- [{NEWER}] total"))
    assert line_older.endswith("shown") and line_newer.endswith("not shown")
