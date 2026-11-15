"""Guard the measured load behavior with a small run of the replay harness."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from cairnkit import followups, hygiene, load, selection, usage

PATH = Path(__file__).parents[1] / "benchmarks" / "forgetting" / "harness.py"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("forgetting_harness", PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _score(harness, scenario: str, label: str = "", seeds: int = 5) -> float:
    hits = needs = 0
    for seed in range(seeds):
        world = harness.SCENARIOS[scenario](seed, 4, 0)
        out = harness.replay(world, harness.BY_NAME["load"], 0.0, seed, 600)
        for row in out["rows"]:
            if not label or row["label"] == label:
                hits += row["text"]
                needs += row["n_need"]
    return hits / needs


def test_a_replay_leaves_the_load_code_as_it_found_it(harness):
    """Other tests in the same process call the real load, so a stub must not outlive a replay."""
    modules = (followups, hygiene, load, selection, usage)
    before = [dict(vars(module)) for module in modules]
    world = harness.SCENARIOS["busy-day"](0, 1, 0)
    harness.replay(world, harness.BY_NAME["load"], 0.0, 0, 600)
    assert [dict(vars(module)) for module in modules] == before


@pytest.mark.parametrize("script", ["clockcheck.py", "fixture_replay.py"])
def test_a_script_for_an_old_commit_names_that_commit(script):
    done = subprocess.run(
        [sys.executable, str(PATH.with_name(script))], capture_output=True, text=True
    )
    assert done.returncode != 0
    assert "2326ea0" in done.stderr
    assert "Traceback" not in done.stderr


def test_a_long_session_finds_its_facts(harness):
    assert _score(harness, "long-session") > 0.7


def test_a_vacation_loses_nothing_it_had(harness):
    assert _score(harness, "vacation-gap60") >= _score(harness, "vacation-gap0") - 0.2


def test_an_old_trap_loads_with_no_signal(harness):
    assert _score(harness, "old-trap", "trap-only:no-signal") > 0.7


def test_an_old_trap_loads_when_its_area_is_in_use(harness):
    assert _score(harness, "old-trap", "trap-only:after-first-commit") == 1.0
