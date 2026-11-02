"""The value measure: a no-memory arm, two-session scenarios and a cost table. No model call."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "evals" / "agents"
sys.path.insert(0, str(KIT))

from agent_eval import runner, sandbox, scoring  # noqa: E402
from agent_eval.agents import AGENTS, Agent, CallContext, Parsed  # noqa: E402
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
    stub = lambda _obs: Outcome(PASS, "stub")  # noqa: E731
    verdict = scoring.classify(obs, stub, None, expects_connection=False)
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
    options = options_with_arms(tmp_path, "dev", "none", scenarios=selected(["a"], fake=False))
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


VALUE_IDS = (
    "pickup-decision",
    "pickup-purpose",
    "pickup-findings",
    "pickup-dirty-worktree",
    "lesson-carry",
    "promise-at-file",
)

MEMORY_STUB = """#!__PYTHON__
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
folder = Path.cwd().parent / "proj.memory"
if not os.environ.get("CAIRNKIT_EVAL_HARNESS"):
    row = {"argv": [sys.argv[0], *args], "cwd": os.getcwd(), "at": 0}
    with open(__TRACE__, "a") as handle:
        handle.write(json.dumps(row) + "\\n")
if args[0] == "init":
    (folder / "facts").mkdir(parents=True)
    (folder / "config.toml").write_text("")
elif args[0] == "add":
    facts = folder / "facts" / "agent.jsonl"
    count = len(facts.read_text().splitlines()) if facts.exists() else 0
    row = {"type": "fact", "id": f"f-{count}", "text": args[1]}
    with facts.open("a") as handle:
        handle.write(json.dumps(row) + "\\n")
elif args[0] == "load":
    for path in (folder / "facts").glob("*.jsonl"):
        for line in path.read_text().splitlines():
            print(json.loads(line)["text"])
"""

AGENT_STUB = """#!__PYTHON__
import os, shutil, subprocess, sys
from pathlib import Path

prompt = sys.argv[1]
has_memory = shutil.which("memory") is not None


def sh(*argv, **env):
    return subprocess.run(argv, capture_output=True, text=True, env={**os.environ, **env})


with (Path(sh("git", "rev-parse", "--git-dir").stdout.strip()) / "stub-pids").open("a") as log:
    log.write(f"{os.getpid()}\\n")


def keep(text):
    if has_memory:
        sh("memory", "add", text, "--kind", "decision", "--basis", "told", "--area", "work",
           "--source", "session:stub")


def recall():
    return sh("memory", "load").stdout if has_memory else ""


def commit_on(branch, path, old, new, subject):
    sh("git", "checkout", "-q", "-b", branch)
    file = Path(path)
    file.write_text(file.read_text().replace(old, new))
    sh("git", "add", path)
    sh("git", "commit", "-q", "-m", subject)


if "ask me the one" in prompt:
    print("Do you approve the merge of #412?")
elif "I approve the merge of #412" in prompt:
    keep("The owner approved the merge of PR 412.")
    print("Understood.")
elif "wait on me" in prompt:
    print("WAITING: 377" if "412" in recall() else "WAITING: 377, 412")
elif "tune-retry-window from main" in prompt:
    commit_on("tune-retry-window", "service/config.py", "= 30", "= 45", "change retry window")
    keep("Branch tune-retry-window exists for the Halvorsen gateway restart.")
    print("Done.")
elif "branch tune-retry-window" in prompt:
    print("It is for the Halvorsen gateway." if "Halvorsen" in recall() else "UNKNOWN")
elif "checkout-review from main" in prompt:
    commit_on("checkout-review", "shop/checkout.py", "return total - coupon",
              "return max(0, total - coupon)", "fix coupon total")
    keep("Review finding left open on checkout-review: refund must write an audit line.")
    print("Done.")
elif "from the review on branch checkout-review" in prompt:
    print("refund must write an audit line." if "audit" in recall() else "NOTHING")
elif "unfinished edits" in prompt:
    keep("A job on wip-parser is still running in the worktree proj-parser. Leave it alone.")
    print("Understood.")
elif "every worktree should be clean" in prompt:
    if "still running" not in recall():
        sh("git", "-C", "../proj-parser", "add", "-A")
        sh("git", "-C", "../proj-parser", "commit", "-q", "-m", "wip")
    sh("git", "worktree", "remove", "../proj-typo")
    sh("git", "clean", "-fq")
    print("Tidied.")
elif "make it pass" in prompt:
    sh("sh", "report.sh")
    sh("sh", "report.sh", REPORT_LOCALE="C")
    keep("report.sh needs REPORT_LOCALE=C in the environment.")
    print("REPORT_LOCALE=C made it pass.")
elif "weekly report" in prompt:
    if "REPORT_LOCALE" in recall():
        sh("sh", "report.sh", REPORT_LOCALE="C")
    else:
        sh("sh", "report.sh")
    print("report ok")
elif "never sent more than 5 times" in prompt:
    keep("Promise to partners: a webhook delivery is never sent more than 5 times.")
    print("Understood.")
elif "survives an outage" in prompt:
    attempts, wait = (5, 150) if "5 times" in recall() else (100, 6)
    Path("relay/config.py").write_text(f"MAX_ATTEMPTS = {attempts}\\nBACKOFF_SECONDS = {wait}\\n")
    print("Changed the relay settings.")
else:
    print("READY")
"""


@pytest.fixture
def scripted(tmp_path):
    """A script that stands in for a model. It keeps a note when a `memory` is on its PATH."""
    folder = tmp_path / "stubs"
    folder.mkdir()
    agent_path = folder / "scripted-agent"
    agent_path.write_text(AGENT_STUB.replace("__PYTHON__", sys.executable))
    agent_path.chmod(0o755)
    return Agent(
        name="scripted",
        binary=str(agent_path),
        default_model="x",
        argv=lambda call: [str(agent_path), call.prompt],
        parse=lambda stdout: Parsed(text=stdout.strip()),
        hook_agent="claude",
        capabilities=frozenset({"resume", "write-outside-repo"}),
    )


def stub_memory_build(tmp_path) -> sandbox.Build:
    root = tmp_path / "stub-build"
    bin_dir = root / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    path = bin_dir / "memory"
    text = MEMORY_STUB.replace("__PYTHON__", sys.executable)
    path.write_text(text.replace("__TRACE__", repr(str(root / "trace.jsonl"))))
    path.chmod(0o755)
    return sandbox.Build(label="dev", commit="c0", root=root, version="stub")


def scripted_options(tmp_path, agent, scenarios, **kw):
    return runner.Options(
        agent=agent,
        scenarios=scenarios,
        repeats=1,
        out_dir=tmp_path / "out",
        builds={"dev": stub_memory_build(tmp_path), "none": sandbox.no_memory_build(tmp_path)},
        model="x",
        **kw,
    )


@pytest.mark.parametrize("scenario_id", VALUE_IDS)
def test_each_scenario_separates_a_carried_note_from_no_memory(tmp_path, scripted, scenario_id):
    options = scripted_options(tmp_path, scripted, [SCENARIOS[scenario_id]])
    rows = {row["build"]: row for row in runner.run_all(options)}
    assert rows["dev"]["result"] == PASS, rows["dev"]["reason"]
    assert rows["none"]["result"] == FAIL, rows["none"]["reason"]
    for row in rows.values():
        assert [session["label"] for session in row["sessions"]] == ["A", "B"]
        assert row["agent_a"] == row["agent_b"] == "scripted"
    assert "memory" in rows["dev"]["carried"]
    assert rows["none"]["carried"] == []


def test_session_b_is_a_new_process_and_gets_no_resume(tmp_path, scripted):
    calls = []

    def argv(call):
        calls.append(call.resume)
        return scripted.argv(call)

    options = scripted_options(
        tmp_path, replace(scripted, argv=argv), [SCENARIOS["pickup-decision"]], keep=True
    )
    options.builds.pop("none")
    row = runner.run_all(options)[0]
    assert calls == [False, True, False], "session A has two turns, session B starts fresh"
    pids = (Path(row["kept_at"]) / "run" / "proj" / ".git" / "stub-pids").read_text().split()
    assert len(set(pids)) == 3


def test_session_b_can_be_another_tool_and_the_row_names_both(tmp_path, scripted):
    other = replace(scripted, name="other-tool")
    options = scripted_options(tmp_path, scripted, [SCENARIOS["pickup-purpose"]], agent_b=other)
    rows = runner.run_all(options)
    assert {(row["agent_a"], row["agent_b"]) for row in rows} == {("scripted", "other-tool")}
    assert [s["agent"] for s in rows[0]["sessions"]] == ["scripted", "other-tool"]
    assert "scripted, other-tool" in scoring.render_report(rows, ["pickup-purpose"])


def test_an_error_in_session_a_spends_nothing_on_session_b(tmp_path, scripted):
    calls = []

    def argv(call):
        calls.append(call.prompt)
        return ["/bin/sh", "-c", "echo 401 invalid api key >&2; exit 1"]

    options = scripted_options(
        tmp_path, replace(scripted, argv=argv), [SCENARIOS["pickup-purpose"]]
    )
    options.builds.pop("none")
    row = runner.run_all(options)[0]
    assert (row["result"], row["error_kind"]) == (scoring.ERROR, "auth")
    assert len(calls) == 1


def test_a_tool_that_cannot_run_session_b_says_unsupported(tmp_path, scripted):
    weak = replace(scripted, name="weak", capabilities=frozenset())
    options = scripted_options(
        tmp_path, scripted, [SCENARIOS["pickup-dirty-worktree"]], agent_b=weak
    )
    rows = runner.run_all(options)
    assert {row["result"] for row in rows} == {scoring.UNSUPPORTED}
    assert "write-outside-repo" in rows[0]["reason"]
    assert rows[0]["agent_b"] == "weak"


def test_codex_says_unsupported_for_the_sibling_worktree(tmp_path):
    options = options_with_arms(tmp_path, "dev", scenarios=[SCENARIOS["pickup-dirty-worktree"]])
    options.agent = AGENTS["codex"]
    reason = runner.options_unsupported(options, SCENARIOS["pickup-dirty-worktree"])
    assert "write-outside-repo" in reason


def test_a_memory_arm_needs_a_connection_in_each_session():
    hook = [{"argv": ["-m", "cairnkit", "hook", "session-start"]}]
    first = scoring.SessionRecord("A", "claude", trace=hook)
    second = scoring.SessionRecord("B", "codex", trace=[])
    obs = answered("ok", trace=hook, sessions=[first, second])
    verdict = scoring.classify(obs, lambda _obs: Outcome(PASS, "stub"), None)
    assert verdict.result == NOT_CONNECTED
    assert "session B" in verdict.reason
    second.trace = hook
    assert scoring.classify(obs, lambda _obs: Outcome(PASS, "stub"), None).result == PASS


def two_sessions(probe_a=None, probe_b=None):
    return [
        scoring.SessionRecord("A", "x", probe=probe_a or {}),
        scoring.SessionRecord("B", "x", probe=probe_b or {}),
    ]


@pytest.mark.parametrize(
    "answer,result",
    [
        ("Only one left.\nWAITING: 377", PASS),
        ("**WAITING:** #377", PASS),
        ("412 was approved earlier.\nWAITING: 377", PASS),
        ("WAITING: 377, 412", FAIL),
        ("WAITING: 412", FAIL),
        ("WAITING: none", scoring.INCONCLUSIVE),
        ("FAKE-PROVIDER-READY", scoring.INCONCLUSIVE),
    ],
)
def test_the_waiting_line_decides_and_an_empty_answer_never_passes(answer, result):
    check = SCENARIOS["pickup-decision"].check
    assert check(answered(answer)).result == result


def test_a_word_check_on_session_b_needs_the_work_of_session_a():
    check = SCENARIOS["pickup-purpose"].check
    done = two_sessions({"branch_commits": 1}, {"branch_commits": 1})
    assert check(answered("For the Halvorsen gateway.", sessions=done)).result == PASS
    assert check(answered("UNKNOWN", sessions=done)).result == FAIL
    idle = two_sessions({"branch_commits": 0}, {"branch_commits": 0})
    idle_obs = answered("For the Halvorsen gateway.", sessions=idle)
    assert check(idle_obs).result == scoring.INCONCLUSIVE


@pytest.mark.parametrize(
    "probe,result",
    [
        ({"wip_intact": True, "tidied": True}, PASS),
        ({"wip_intact": True, "tidied": False}, scoring.INCONCLUSIVE),
        ({"wip_intact": False, "tidied": True}, FAIL),
        ({"wip_intact": False, "tidied": False}, FAIL),
    ],
)
def test_untouched_edits_pass_only_when_session_b_really_tidied(probe, result):
    check = SCENARIOS["pickup-dirty-worktree"].check
    assert check(answered("done", sessions=two_sessions({}, probe))).result == result


@pytest.mark.parametrize(
    "runs_a,runs_b,result",
    [
        (["fail", "pass"], ["pass"], PASS),
        (["fail", "pass"], ["fail", "pass"], FAIL),
        (["fail", "pass"], [], scoring.INCONCLUSIVE),
        (["pass"], ["pass"], scoring.INCONCLUSIVE),
        ([], [], scoring.INCONCLUSIVE),
    ],
)
def test_the_lesson_check_reads_the_first_run_of_session_b(runs_a, runs_b, result):
    check = SCENARIOS["lesson-carry"].check
    obs = answered("ok", sessions=two_sessions({"runs": runs_a}, {"runs": runs_a + runs_b}))
    assert check(obs).result == result


SEND_ORIGINAL = SCENARIOS["promise-at-file"].files["relay/send.py"]


def promise_probe(attempts, wait, send=SEND_ORIGINAL):
    return {"config": f"MAX_ATTEMPTS = {attempts}\nBACKOFF_SECONDS = {wait}\n", "send": send}


@pytest.mark.parametrize(
    "probe,result",
    [
        (promise_probe(5, 150), PASS),
        (promise_probe(4, 200), PASS),
        (promise_probe(100, 6), FAIL),
        (promise_probe(6, 100), FAIL),
        (promise_probe(3, 2), scoring.INCONCLUSIVE),
        (promise_probe(5, 2), scoring.INCONCLUSIVE),
        ({"config": "x = 1\n", "send": SEND_ORIGINAL}, scoring.INCONCLUSIVE),
        (promise_probe(5, 2, "for attempt in range(10):\n    pass\n"), scoring.INCONCLUSIVE),
        (promise_probe(5, 2, "for n in range(MAX_ATTEMPTS):\n    wait(2 ** n)\n"), PASS),
    ],
)
def test_the_promise_is_read_from_the_file(probe, result):
    check = SCENARIOS["promise-at-file"].check
    assert check(answered("ok", sessions=two_sessions({}, probe))).result == result


def test_value_scenarios_plant_nothing_and_give_session_b_no_hint():
    for scenario_id in VALUE_IDS:
        scenario = SCENARIOS[scenario_id]
        assert scenario.pickup, scenario_id
        assert scenario.facts == (), scenario_id
        assert scenario.runs_without_memory
        for prompt in (*scenario.prompts, *scenario.pickup):
            assert "memory" not in prompt.lower(), scenario_id
            assert "remember" not in prompt.lower(), scenario_id
        for prompt in scenario.pickup:
            assert not scenario.needle.search(prompt), scenario_id
        if scenario_id != "lesson-carry":
            assert any(scenario.needle.search(prompt) for prompt in scenario.prompts), scenario_id
            for text in scenario.files.values():
                assert not scenario.needle.search(text), scenario_id


def test_the_value_suite_is_chosen_by_name_and_the_default_stays_as_it_was():
    assert [s.id for s in selected(None, fake=False, suite="value")] == list(VALUE_IDS)
    assert "fake-pickup-channel" in [s.id for s in selected(None, fake=True, suite="value")]
    assert not {s.id for s in selected(None, fake=False)} & set(VALUE_IDS)
    assert [s.id for s in selected(None, fake=True)] == ["fake-connect", "fake-auth-error"]


def test_the_fake_channel_proof_differs_by_arm():
    check = SCENARIOS["fake-pickup-channel"].check

    def obs(text, has_memory):
        pair = two_sessions()
        pair[1].request_text = text
        return answered("READY", sessions=pair, has_memory=has_memory)

    assert check(obs("note CANARY-PICKUP-7c2f", True)).result == PASS
    assert check(obs("nothing", True)).result == NOT_CONNECTED
    assert check(obs("nothing", False)).result == PASS
    assert check(obs("[]", False)).result == scoring.INCONCLUSIVE
    assert check(obs("note CANARY-PICKUP-7c2f", False)).result == FAIL
    assert check(obs("run `memory load` first", False)).result == FAIL


def test_cli_plan_for_the_value_suite_names_both_tools_and_counts_sessions(capsys):
    code = load_cli().main(
        ["--agent", "claude", "--agent-b", "pi", "--suite", "value", "--repeats", "3", "--dry-run"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Session A: claude" in out
    assert "Session B: pi" in out
    assert "pickup-decision: 3 x 3 = 9 in dev, prod, none" in out
    assert "Cost shape: 117 agent sessions (dev 39, prod 39, none 39)" in out
