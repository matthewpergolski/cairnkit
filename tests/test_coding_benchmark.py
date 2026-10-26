"""The coding mini-benchmark: a made-up web service with about 100 notes and 58 probes.

These are regression floors and sanity checks, not a claim about real use. The floors sit
below the numbers measured when the fixture was frozen, so a small change in the code does
not break them, and a broken ranker does.
"""

import importlib.util
import time
from collections import Counter
from pathlib import Path

from cairnkit.schema import validate_record
from cairnkit.store import fact_files, read_records

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "benchmarks" / "fixtures" / "coding"


def load_harness():
    spec = importlib.util.spec_from_file_location(
        "retrieval_eval", ROOT / "benchmarks" / "retrieval_eval.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HARNESS = load_harness()
PROBES = HARNESS.read_probes(FIXTURE / "probes.jsonl")
FRAGMENTS = HARNESS.read_probes(FIXTURE / "probes_fragments.jsonl")


def test_every_record_is_valid_and_ids_are_unique():
    records, errors = read_records(fact_files(FIXTURE))
    assert errors == []
    for rec in records:
        assert validate_record(rec) == [], rec
    ids = [r["id"] for r in records if r["type"] == "fact"]
    assert len(ids) == len(set(ids))


def test_the_fixture_is_big_enough_that_the_top_five_is_not_trivial():
    facts = HARNESS.load_facts(FIXTURE)
    assert 80 <= len(facts) <= 120
    assert 40 <= len(PROBES) <= 60
    assert len(HARNESS.load_facts(FIXTURE, include_ended=True)) > len(facts)


def test_the_probes_cover_the_kinds_with_enough_stale_and_decoy_cases():
    kinds = Counter(p["kind"] for p in PROBES)
    assert set(kinds) == {"decision", "fix", "convention", "preference", "stale"}
    assert all(n >= 10 for n in kinds.values())
    assert sum(bool(p["stale"]) for p in PROBES) >= 10
    assert sum(bool(p["decoy"]) for p in PROBES) >= 20
    assert len(FRAGMENTS) == 10 and {p["kind"] for p in FRAGMENTS} == {"fragment"}


def test_some_stale_facts_are_marked_superseded_and_some_are_not():
    facts = HARNESS.load_facts(FIXTURE)
    active = {s["id"] for s in facts}
    stale = {i for p in PROBES for i in p["stale"]}
    assert stale & active and stale - active  # a mix, as in real use


def test_many_probes_share_few_words_with_their_answer():
    by_id = {s["id"]: s for s in HARNESS.load_facts(FIXTURE)}
    low = sum(HARNESS.overlap(p, by_id) <= 1 for p in PROBES)
    assert low >= 15


def test_the_controls_prove_the_harness_can_tell_good_from_bad():
    results = HARNESS.evaluate(FIXTURE, PROBES)
    floor = results["random-mean"]
    assert results["oracle"]["any@1"] == 1.0 and results["oracle"]["all@5"] == 1.0
    for control in ("inverted", "mismatched-query"):
        assert results[control]["any@5"] <= floor["any@5"] + 0.1
        assert results[control]["any@1"] <= 0.1
    assert results["cairnkit"]["any@1"] > 5 * max(floor["any@1"], 0.01)


def test_search_stays_above_the_floors_measured_at_the_freeze():
    results = HARNESS.evaluate(FIXTURE, PROBES)
    best, count = results["cairnkit"], results["keyword-count"]
    assert best["any@1"] >= 0.45 and best["any@5"] >= 0.7
    assert best["any@1"] > count["any@1"] and best["any@5"] > count["any@5"]
    assert results["random-mean"]["any@5"] < 0.15
    assert best["empty"] == 0


def test_the_difference_from_keyword_count_holds_up_under_resampling():
    facts = HARNESS.load_facts(FIXTURE)
    outcomes = HARNESS.search_outcomes(facts, PROBES)
    paired = HARNESS.compare(outcomes, "cairnkit", "keyword-count", "any1")
    assert paired["n"] == len(PROBES) and paired["ci95"][0] > 0


def test_the_fallback_finds_word_fragments_that_whole_word_search_cannot():
    results = HARNESS.evaluate(FIXTURE, FRAGMENTS)
    assert results["cairnkit"]["any@5"] == 1.0
    assert results["cairnkit-whole-word"]["any@5"] == 0.0 and results["strict"]["any@5"] == 1.0


def test_the_fallback_changes_nothing_on_ordinary_questions():
    results = HARNESS.evaluate(FIXTURE, PROBES)
    assert results["cairnkit"] == results["cairnkit-whole-word"]


def test_load_beats_random_fill_and_never_loads_a_superseded_fact():
    for budget in (300, 600, 1200):
        rows = HARNESS.evaluate_load(FIXTURE, PROBES, budget)
        assert rows["cairnkit"]["gold@load"] >= rows["random-fill"]["gold@load"]
        assert rows["cairnkit"]["stale-leak"] <= rows["random-fill"]["stale-leak"]
    all_rows = HARNESS.evaluate_load(FIXTURE, PROBES, 0)
    assert all_rows["cairnkit"]["gold@load"] == 1.0  # no limit loads every active fact


def test_the_whole_report_runs_in_a_few_seconds():
    start = time.monotonic()
    HARNESS.report(FIXTURE, PROBES, 0, [300, 600, 1200])
    assert time.monotonic() - start < 30
