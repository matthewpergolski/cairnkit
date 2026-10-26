"""The retrieval harness in benchmarks/ runs on the synthetic fixture and its numbers hold."""

import importlib.util
import json
from pathlib import Path

import pytest
from conftest import make_fact, write_facts

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "benchmarks" / "fixtures" / "synthetic"


def load_harness():
    spec = importlib.util.spec_from_file_location(
        "retrieval_eval", ROOT / "benchmarks" / "retrieval_eval.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate(seed=0):
    harness = load_harness()
    probes = harness.read_probes(FIXTURE / "probes.jsonl")
    return harness.evaluate(FIXTURE, probes, seed)


def test_the_fixture_has_a_dozen_notes_and_probes():
    harness = load_harness()
    assert len(harness.read_probes(FIXTURE / "probes.jsonl")) >= 12
    assert len(harness.load_facts(FIXTURE)) >= 12


def test_every_system_reports_the_three_numbers():
    results = evaluate()
    assert list(results) == ["cairnkit", "strict", "keyword-count", "random"]
    for numbers in results.values():
        assert set(numbers) == {"any@1", "any@5", "all@5"}
        assert all(0.0 <= v <= 1.0 for v in numbers.values())


def test_the_numbers_are_the_same_on_every_run():
    assert evaluate() == evaluate()


def test_cairnkit_search_beats_the_baselines_and_the_old_search():
    results = evaluate()
    best = results["cairnkit"]
    for other in ("strict", "keyword-count", "random"):
        assert best["any@1"] > results[other]["any@1"]
    for other in ("strict", "random"):
        assert best["any@5"] > results[other]["any@5"]
    assert best["any@5"] >= results["keyword-count"]["any@5"]
    assert results["strict"]["any@5"] == 0.0  # a question holds the words of no single note


def test_floors_of_cairnkit_search_on_the_fixture():
    best = evaluate()["cairnkit"]
    assert best["any@1"] >= 0.9
    assert best["any@5"] >= 0.95
    assert best["all@5"] >= 0.95


def test_ended_facts_are_not_in_the_corpus():
    harness = load_harness()
    ids = {s["id"] for s in harness.load_facts(FIXTURE)}
    assert "f-20261001-0014" not in ids


def test_the_command_line_prints_a_table_and_json(capsys):
    harness = load_harness()
    probes = str(FIXTURE / "probes.jsonl")
    assert harness.main([str(FIXTURE), probes]) == 0
    table = capsys.readouterr().out
    assert "any@1" in table and "cairnkit" in table and "random" in table
    assert harness.main([str(FIXTURE), probes, "--json"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == {
        "cairnkit",
        "strict",
        "keyword-count",
        "random",
    }


# --- load mode, stale and decoy facts, controls, splits and the bootstrap ---


def probe(question, gold, **extra):
    return {
        "question": question,
        "gold": set(gold),
        "stale": set(extra.get("stale", ())),
        "decoy": set(extra.get("decoy", ())),
        "kind": extra.get("kind", "general"),
    }


def small_memory(mem):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Queue jobs retry five times with backoff.", area="queue"),
            make_fact("f-20261001-0002", "Email retries use a fixed delay.", area="email"),
            make_fact("f-20261001-0003", "Releases are cut from the main branch.", area="ci"),
            make_fact("f-20261001-0004", "Old: releases came from a release branch.", area="ci"),
            make_fact(
                "f-20261001-0005",
                "Short lived freeze.",
                scope="short",
                expires_at="2026-10-10T00:00:00+00:00",
            ),
            {
                "type": "change",
                "id": "f-20261001-0004",
                "at": "2026-10-02T00:00:00+00:00",
                "status": "superseded",
                "superseded_by": "f-20261001-0003",
                "reason": "The release branch is gone.",
                "writer": "main",
            },
        ],
    )
    return mem


def test_probes_may_name_stale_and_decoy_facts_and_a_kind(tmp_path):
    path = tmp_path / "p.jsonl"
    path.write_text(
        json.dumps(
            {
                "question": "q?",
                "gold_note_ids": ["a"],
                "stale_note_ids": ["b"],
                "decoy_note_ids": ["c"],
                "kind": "fix",
            }
        )
        + "\n"
        + json.dumps({"question": "r?", "gold_note_ids": ["a"]})
        + "\n"
    )
    first, second = load_harness().read_probes(path)
    assert (first["stale"], first["decoy"], first["kind"]) == ({"b"}, {"c"}, "fix")
    assert (second["stale"], second["decoy"], second["kind"]) == (set(), set(), "general")


def test_a_probe_that_names_a_missing_fact_is_an_error(mem):
    harness = load_harness()
    small_memory(mem)
    with pytest.raises(ValueError, match="f-20261001-0099"):
        harness.evaluate(mem, [probe("q", ["f-20261001-0099"])])


def test_ended_facts_are_in_the_corpus_only_with_include_ended(mem):
    harness = load_harness()
    small_memory(mem)
    assert "f-20261001-0004" not in {s["id"] for s in harness.load_facts(mem)}
    assert "f-20261001-0004" in {s["id"] for s in harness.load_facts(mem, include_ended=True)}


def test_the_corpus_does_not_depend_on_the_real_clock(mem, monkeypatch):
    harness = load_harness()
    small_memory(mem)
    expected = {s["id"] for s in harness.load_facts(mem)}
    assert "f-20261001-0005" not in expected  # ended before the pinned time
    monkeypatch.setenv("MEMORY_NOW", "2020-01-01T00:00:00+00:00")
    assert {s["id"] for s in harness.load_facts(mem)} == expected


def test_stale_facts_that_outrank_gold_are_counted(mem):
    harness = load_harness()
    small_memory(mem)
    p = probe("Which branch do releases come from?", ["f-20261001-0003"], stale=["f-20261001-0004"])
    shown = harness.evaluate(mem, [p], include_ended=True)["cairnkit"]
    assert shown["any@1"] == 1.0 and shown["stale>gold"] == 0.0
    # keyword-count ranks the longer stale text with more of the words first
    bad = probe("release branch", ["f-20261001-0003"], stale=["f-20261001-0004"])
    row = harness.evaluate(mem, [bad], include_ended=True)["keyword-count"]
    assert row["stale>gold"] == 1.0 and row["stale@5"] == 1.0


def test_the_oracle_scores_one_and_the_broken_controls_score_low(mem):
    harness = load_harness()
    small_memory(mem)
    probes = [
        probe("How often do queue jobs retry?", ["f-20261001-0001"]),
        probe("What is the email retry delay?", ["f-20261001-0002"]),
        probe("Where do releases come from?", ["f-20261001-0003"]),
    ]
    results = harness.evaluate(mem, probes)
    assert results["oracle"]["any@1"] == 1.0 and results["oracle"]["all@5"] == 1.0
    assert results["cairnkit"]["any@1"] == 1.0
    assert results["inverted"]["any@1"] < results["cairnkit"]["any@1"]
    assert results["mismatched-query"]["any@1"] < results["cairnkit"]["any@1"]


def test_every_system_reports_an_empty_count(mem):
    harness = load_harness()
    small_memory(mem)
    results = harness.evaluate(mem, [probe("kubernetes", ["f-20261001-0001"])])
    assert results["cairnkit"]["empty"] == 1
    assert results["random"]["empty"] == 0


def test_the_fallback_system_finds_a_part_of_a_word_and_the_whole_word_one_does_not(mem):
    harness = load_harness()
    write_facts(mem, [make_fact("f-20261001-0001", "Production deployment needs approval.")])
    results = harness.evaluate(mem, [probe("deploy", ["f-20261001-0001"])])
    assert results["cairnkit"]["any@1"] == 1.0
    assert results["cairnkit-whole-word"]["any@1"] == 0.0


def load_rows(mem, probes, budget):
    return load_harness().evaluate_load(mem, probes, budget)


def test_load_mode_reports_whether_gold_is_in_the_budget(mem):
    small_memory(mem)
    probes = [probe("q", ["f-20261001-0001"]), probe("q", ["f-20261001-0003"])]
    wide = load_rows(mem, probes, budget=0)["cairnkit"]
    assert wide["gold@load"] == 1.0 and wide["gold-all@load"] == 1.0
    tight = load_rows(mem, probes, budget=15)["cairnkit"]
    assert tight["facts"] == 1 and tight["gold@load"] == 0.5


def test_load_mode_does_not_load_superseded_facts_and_counts_unlinked_stale_ones(mem):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Deploys run from main."),
            make_fact("f-20261001-0002", "Deploys run from release."),
        ],
    )
    p = probe("q", ["f-20261001-0001"], stale=["f-20261001-0002"])
    row = load_rows(mem, [p], budget=0)["cairnkit"]
    assert row["stale-leak"] == 1.0 and row["stale-loaded"] == 1.0
    small_memory(mem)
    p2 = probe("q", ["f-20261001-0003"], stale=["f-20261001-0004"])
    assert load_rows(mem, [p2], budget=0)["cairnkit"]["stale-leak"] == 0.0


def test_load_mode_does_not_depend_on_the_clock_or_the_writer(mem, monkeypatch):
    small_memory(mem)
    probes = [probe("q", ["f-20261001-0001"])]
    first = load_rows(mem, probes, budget=15)
    monkeypatch.setenv("MEMORY_NOW", "2030-01-01T00:00:00+00:00")
    monkeypatch.setenv("MEMORY_WRITER", "someone-else")
    assert load_rows(mem, probes, budget=15) == first


def test_load_mode_has_floors_to_beat(mem):
    small_memory(mem)
    rows = load_rows(mem, [probe("q", ["f-20261001-0001"])], budget=15)
    assert set(rows) == {"cairnkit", "newest-first", "random-fill"}


def test_bootstrap_of_a_clear_gain_excludes_zero_and_is_repeatable():
    harness = load_harness()
    better = [1] * 40 + [0] * 10
    worse = [0] * 30 + [1] * 10 + [0] * 10
    delta, low, high = harness.bootstrap_delta(better, worse)
    assert delta == pytest.approx(0.6) and 0 < low < delta < high
    assert harness.bootstrap_delta(better, worse) == (delta, low, high)


def test_bootstrap_of_equal_systems_is_zero_and_straddles_zero():
    harness = load_harness()
    flags = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1]
    swapped = [0, 1, 1, 0, 1, 0, 1, 1, 0, 1]
    assert harness.bootstrap_delta(flags, flags) == (0.0, 0.0, 0.0)
    delta, low, high = harness.bootstrap_delta(flags, swapped)
    assert delta == 0.0 and low < 0 < high


def test_groups_with_fewer_than_ten_probes_are_flagged(mem):
    harness = load_harness()
    small_memory(mem)
    probes = [probe("queue retry", ["f-20261001-0001"], kind="fix")] * 10 + [
        probe("email delay", ["f-20261001-0002"], kind="decision")
    ] * 3
    groups = harness.split_by_kind(mem, probes)
    assert groups["fix"]["n"] == 10 and not groups["fix"]["unreliable"]
    assert groups["decision"]["n"] == 3 and groups["decision"]["unreliable"]
    assert groups["fix"]["cairnkit"]["any@1"] == 1.0
