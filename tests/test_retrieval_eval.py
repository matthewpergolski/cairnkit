"""The retrieval harness in benchmarks/ runs on the synthetic fixture and its numbers hold."""

import importlib.util
import json
from pathlib import Path

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
