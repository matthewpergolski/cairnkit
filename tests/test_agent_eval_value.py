"""The value measure: a no-memory arm, two-session scenarios and a cost table. No model call."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "evals" / "agents"
sys.path.insert(0, str(KIT))

from agent_eval import runner, sandbox, scoring  # noqa: E402
from agent_eval.agents import AGENTS, CallContext, Parsed  # noqa: E402
from agent_eval.scenarios import SCENARIOS, selected  # noqa: E402
from agent_eval.scoring import FAIL, NOT_CONNECTED, PASS, Observation, Outcome, Turn  # noqa: E402


def load_cli():
    spec = importlib.util.spec_from_file_location("agent_eval_run_value", KIT / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def answered(text: str, **kw) -> Observation:
    return Observation(turns=[Turn(0, "", "", Parsed(text=text))], **kw)


def test_the_no_memory_arm_installs_nothing_and_hides_a_memory_on_path(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("memory", "cairnkit", "other-tool"):
        path = tools / name
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([str(tools), os.environ["PATH"]]))

    build = sandbox.no_memory_build(tmp_path / "builds")
    box = sandbox.make_sandbox(
        build,
        AGENTS["claude"],
        SCENARIOS["a-fact-at-start"],
        tmp_path / "run",
        isolated_home=True,
    )

    assert not box.memory_dir.exists()
    assert box.connect_steps == []
    assert box.git_status() == []
    assert not (box.repo / ".claude").exists()
    assert not (box.repo / "memory-bank").exists()
    hooks = [p.name for p in (box.repo / ".git" / "hooks").iterdir() if p.suffix != ".sample"]
    assert hooks == []
    assert shutil.which("memory", path=box.env["PATH"]) is None
    assert shutil.which("cairnkit", path=box.env["PATH"]) is None
    assert shutil.which("other-tool", path=box.env["PATH"]) is not None


def test_a_command_with_no_memory_folder_gets_no_memory_path(tmp_path):
    for agent in AGENTS.values():
        argv = agent.argv(CallContext("hello", tmp_path, None, "small"))
        assert "--add-dir" not in argv, agent.name
        assert "None" not in argv, agent.name
    with_folder = CallContext("hello", tmp_path, tmp_path / "x.memory", "small")
    assert str(tmp_path / "x.memory") in AGENTS["claude"].argv(with_folder)


def test_the_no_memory_arm_is_scored_with_no_connection_evidence():
    check = lambda _obs: Outcome(PASS, "stub")  # noqa: E731
    assert scoring.classify(answered("ok"), check, None).result == NOT_CONNECTED
    verdict = scoring.classify(answered("ok"), check, None, expects_connection=False)
    assert verdict.result == PASS


def test_an_account_error_is_still_an_error_in_the_no_memory_arm():
    refused = Parsed(is_error=True, error_text="401 invalid api key")
    obs = Observation(turns=[Turn(1, "", "", refused)])
    verdict = scoring.classify(obs, lambda _obs: Outcome(PASS, "stub"), None, expects_connection=False)
    assert (verdict.result, verdict.error_kind) == (scoring.ERROR, "auth")


def row(build: str, result: str, scenario: str = "s1", **kw) -> dict:
    common = {"agent": "claude", "mode": "real", "commit": "abcdef1", "build_version": "v"}
    return {**common, "build": build, "scenario": scenario, "result": result, **kw}


def test_report_shows_every_arm_side_by_side_with_the_no_memory_arm_last():
    rows = [
        row("none", FAIL),
        row("prod", PASS),
        row("dev-instructions", PASS),
        row("dev", PASS),
        row("dev", FAIL),
    ]
    lines = scoring.render_report(rows, ["s1"]).splitlines()
    header = next(line for line in lines if line.startswith("| Scenario"))
    cells = [cell.strip() for cell in header.split("|")]
    assert cells[2:6] == ["dev", "prod", "dev-instructions", "none"]
    body = next(line for line in lines if line.startswith("| s1"))
    assert [cell.strip() for cell in body.split("|")][2:6] == [
        "1 pass, 1 fail, n=2",
        "1 pass, 0 fail, n=1",
        "1 pass, 0 fail, n=1",
        "0 pass, 1 fail, n=1",
    ]


def options_with_arms(tmp_path, *labels, **kw):
    class Stub:
        version = "v"
        commit = "abc"
        has_memory = True

    class StubNone(Stub):
        has_memory = False

    builds = {label: (StubNone() if label == "none" else Stub()) for label in labels}
    return runner.Options(
        agent=AGENTS["pi"],
        repeats=1,
        out_dir=tmp_path,
        builds=builds,
        model="small",
        **kw,
    )


def test_a_planted_fact_scenario_gets_no_run_in_the_no_memory_arm(tmp_path, monkeypatch):
    seen = []

    def trial(options, build, scenario, repeat):
        seen.append(build)
        row_data = runner.base_row(options, build, scenario, repeat)
        return {**row_data, "result": PASS, "reason": "stub"}

    monkeypatch.setattr(runner, "run_trial", trial)
    options = options_with_arms(
        tmp_path, "dev", "prod", "none", scenarios=selected(["a"], fake=False)
    )
    rows = runner.run_all(options)
    assert seen == ["dev", "prod"]
    assert sorted(item["build"] for item in rows) == ["dev", "prod"]


def test_plan_counts_each_arm_and_names_the_extra_arm(tmp_path):
    options = options_with_arms(
        tmp_path, "dev", "none", scenarios=selected(["a"], fake=False)
    )
    refs = {"dev": "HEAD", "dev-enforce": "abc123", "none": None}
    plan = runner.plan_text(options, refs)
    assert "dev-enforce = abc123" in plan
    assert "none = no memory" in plan
    assert "Cost shape: 2 agent sessions" in plan


def test_cli_dry_run_takes_an_extra_arm_and_can_skip_one(capsys):
    code = load_cli().main(
        ["--agent", "pi", "--dry-run", "--arm", "dev-enforce=abc123", "--skip-arm", "prod"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "dev-enforce = abc123" in out
    assert "prod =" not in out


@pytest.mark.parametrize("bad", ["none=HEAD", "dev=HEAD", "no-equals", "bad/label=HEAD", "=HEAD"])
def test_cli_refuses_a_bad_arm(capsys, bad):
    assert load_cli().main(["--agent", "pi", "--dry-run", "--arm", bad]) == 2
    assert "--arm" in capsys.readouterr().err


def test_cli_refuses_two_arms_on_one_commit(capsys):
    argv = ["--agent", "pi", "--arm", "dev-copy=HEAD", "--load-only"]
    assert load_cli().main(argv) == 2
    assert "same commit" in capsys.readouterr().err
