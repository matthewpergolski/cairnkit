"""The agent eval kit reads recorded output correctly. No real agent and no model call."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "evals" / "agents"
sys.path.insert(0, str(KIT))

from agent_eval import runner, scoring  # noqa: E402
from agent_eval.agents import AGENTS, CallContext, Parsed, forbidden_in  # noqa: E402
from agent_eval.fake_provider import FakeProvider, model_requests  # noqa: E402
from agent_eval.scenarios import SCENARIOS, selected  # noqa: E402
from agent_eval.scoring import (  # noqa: E402
    ERROR,
    FAIL,
    INCONCLUSIVE,
    NOT_CONNECTED,
    PASS,
    Observation,
    Outcome,
    Turn,
)

NEEDLE = SCENARIOS["a-fact-at-start"].needle
HOOK_RAN = [{"argv": ["-m", "cairnkit", "hook", "session-start", "--agent", "claude"]}]

# Recorded from the real tools against the fake provider, cut to the lines the parsers read.
CLAUDE_OK = (
    '{"type":"assistant","message":{"model":"fake-small","content":[{"type":"tool_use",'
    '"name":"Bash"},{"type":"text","text":"working"}]}}\n'
    '{"modelUsage":{"fake-small":{"inputTokens":1}},"subagent_stats":{"spawned":2},'
    '"is_error":false,"subtype":"success","result":"Port 7643.","type":"result"}\n'
)
CLAUDE_AUTH = (
    '{"is_error":true,"subtype":"success","api_error_status":401,"type":"result",'
    '"result":"Failed to authenticate. API Error: 401 invalid api key"}\n'
)
CODEX_OK = (
    '{"type":"thread.started","thread_id":"x"}\n'
    '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"Port 7643."}}\n'
    '{"type":"turn.completed","usage":{"input_tokens":1}}\n'
)
CODEX_AUTH = '{"type":"turn.failed","error":{"message":"unexpected status 401 Unauthorized"}}\n'
OPENCODE_OK = (
    '{"type":"step_start","part":{"type":"step-start"}}\n'
    '{"type":"text","part":{"type":"text","text":"Port 7643."}}\n'
    '{"type":"tool_use","part":{"tool":"task"}}\n'
)
OPENCODE_AUTH = '{"type":"error","error":{"data":{"message":"invalid api key"}}}\n'
PI_OK = (
    '{"type":"turn_end","message":{"role":"assistant","model":"fake-small","stopReason":"stop",'
    '"content":[{"type":"text","text":"Port 7643."}]}}\n'
)
PI_AUTH = (
    '{"type":"turn_end","message":{"role":"assistant","stopReason":"error","content":[],'
    '"errorMessage":"401 invalid api key"}}\n'
)
GROK_AUTH = '{"type":"error","message":"Not signed in. To authenticate, run grok login."}\n'
CURSOR_AUTH_STDERR = "Warning: The provided API key is invalid.\n"
CURSOR_TRUST_STDERR = "Workspace Trust Required. Run with --trust or trust this workspace.\n"


def turn(parsed: Parsed | None = None, exit_code: int = 0, stdout="", stderr="", **kw) -> Turn:
    return Turn(exit_code, stdout, stderr, parsed or Parsed(text="ok"), **kw)


def observed(text="ok", *, trace=None, **kw) -> Observation:
    return Observation(turns=[turn(Parsed(text=text))], trace=trace or [], **kw)


def always(result) -> scoring.Outcome:
    return lambda _obs: Outcome(result, "stub")


@pytest.mark.parametrize(
    "agent,stdout,text",
    [
        ("claude", CLAUDE_OK, "Port 7643."),
        ("codex", CODEX_OK, "Port 7643."),
        ("opencode", OPENCODE_OK, "Port 7643."),
        ("pi", PI_OK, "Port 7643."),
    ],
)
def test_parsers_find_the_final_text(agent, stdout, text):
    assert AGENTS[agent].parse(stdout).text == text


def test_claude_parser_reads_model_tools_and_subagents():
    parsed = AGENTS["claude"].parse(CLAUDE_OK)
    assert parsed.model == "fake-small"
    assert parsed.tool_names == ["Bash"]
    assert parsed.subagents == 2


@pytest.mark.parametrize(
    "agent,stdout,stderr,code",
    [
        ("claude", CLAUDE_AUTH, "", 1),
        ("codex", CODEX_AUTH, "", 1),
        ("opencode", OPENCODE_AUTH, "", 1),
        ("pi", PI_AUTH, "", 0),
        ("grok", GROK_AUTH, "", 1),
        ("cursor-agent", "", CURSOR_AUTH_STDERR, 1),
    ],
)
def test_an_account_error_reads_as_error_and_not_as_fail(agent, stdout, stderr, code):
    obs = Observation(turns=[turn(AGENTS[agent].parse(stdout), code, stdout, stderr)])
    verdict = scoring.classify(obs, always(FAIL), NEEDLE)
    assert verdict.result == ERROR
    assert verdict.error_kind == "auth"


def test_a_rate_limit_is_an_account_error_of_its_own_kind():
    parsed = Parsed(is_error=True, error_text="429 rate limit reached")
    verdict = scoring.classify(Observation(turns=[turn(parsed, 1)]), always(FAIL), NEEDLE)
    assert (verdict.result, verdict.error_kind) == (ERROR, "quota")


def test_a_tool_that_retries_a_refused_token_until_the_limit_reads_as_auth():
    stdout = (
        '{"type":"system","subtype":"api_retry","attempt":8,"error_status":401,'
        '"error":"authentication_failed"}\n'
    )
    parsed = AGENTS["claude"].parse(stdout)
    obs = Observation(turns=[turn(parsed, None, stdout, timed_out=True)])
    assert scoring.classify(obs, always(FAIL), NEEDLE).error_kind == "auth"


def test_a_trust_stop_reads_as_not_connected_and_not_as_a_pass():
    obs = Observation(turns=[turn(Parsed(), 1, "", CURSOR_TRUST_STDERR)], trace=HOOK_RAN)
    assert scoring.classify(obs, always(PASS), NEEDLE).result == NOT_CONNECTED


def test_no_evidence_reads_as_not_connected_even_when_the_check_would_pass():
    obs = observed("READY")
    assert scoring.classify(obs, always(PASS), NEEDLE).result == NOT_CONNECTED


def test_a_selectivity_pass_needs_a_connection():
    obs = observed("done", worked_file_changed=True)
    assert scoring.classify(obs, scoring.check_no_junk, None).result == NOT_CONNECTED
    obs.trace = HOOK_RAN
    assert scoring.classify(obs, scoring.check_no_junk, None).result == PASS


def test_a_hook_event_counts_as_connected_and_the_check_decides():
    obs = observed("I do not know.", trace=HOOK_RAN)
    verdict = scoring.classify(obs, scoring.check_answer_has(NEEDLE), NEEDLE)
    assert verdict.result == FAIL


def test_an_agent_lookup_counts_as_connected():
    obs = observed("Port 7643.", trace=[{"argv": ["/x/bin/memory", "search", "port"]}])
    assert scoring.connection_evidence(obs, NEEDLE) == ["agent-ran-lookup", "fact-in-answer"]


def test_a_model_that_says_401_in_a_good_answer_is_not_an_error():
    text = "The handler returns 401 when the API key is missing, and the port is 7643."
    obs = observed(text, trace=HOOK_RAN)
    assert scoring.classify(obs, scoring.check_answer_has(NEEDLE), NEEDLE).result == PASS


def test_a_timeout_and_empty_output_are_errors():
    slow = Observation(turns=[turn(Parsed(), None, timed_out=True)])
    assert scoring.classify(slow, always(PASS), NEEDLE).error_kind == "timeout"
    empty = Observation(turns=[turn(Parsed(text=""))], trace=HOOK_RAN)
    assert scoring.classify(empty, always(PASS), NEEDLE).error_kind == "empty-output"


def test_a_provider_refusal_that_reads_as_success_fails_the_auth_proof():
    verdict = scoring.classify(observed("ok"), always(PASS), NEEDLE, expects_error=True)
    assert verdict.result == FAIL


def test_fake_provider_delivery_levels():
    needle = SCENARIOS["fake-connect"].needle
    check = SCENARIOS["fake-connect"].check
    has_fact = observed(request_text="note CANARY-FACT-5e1a here")
    has_rules = observed(request_text="run `memory load` first")
    has_none = observed(request_text="just a system prompt")
    assert scoring.classify(has_fact, check, needle).result == PASS
    only_rules = scoring.classify(has_rules, check, needle)
    assert only_rules.result == NOT_CONNECTED
    assert "only the rules" in only_rules.reason
    assert scoring.classify(has_none, check, needle).result == NOT_CONNECTED


def test_wrong_trap_passes_only_when_the_fact_left_active():
    check = scoring.check_fact_corrected("trap")
    assert check(observed(seed_ids={"trap": "f-1"}, fact_status={"f-1": "wrong"})).result == PASS
    assert check(observed(seed_ids={"trap": "f-1"}, fact_status={"f-1": "active"})).result == FAIL


def test_fix_fact_needs_a_repeated_failure_and_the_fix_in_a_new_fact():
    needle = SCENARIOS["fake-connect"].needle
    check = scoring.check_wrote_useful_fact(needle)
    useful = [{"text": "needs CANARY-FACT-5e1a"}]
    assert check(observed(report_runs=["fail", "pass"], new_facts=useful)).result == INCONCLUSIVE
    runs = ["fail", "fail", "pass"]
    assert check(observed(report_runs=runs, new_facts=useful)).result == PASS
    assert check(observed(report_runs=runs, new_facts=[{"text": "ran it"}])).result == FAIL


def test_selectivity_needs_the_work_done_and_no_new_fact():
    assert scoring.check_no_junk(observed()).result == INCONCLUSIVE
    done = {"worked_file_changed": True}
    assert scoring.check_no_junk(observed(**done)).result == PASS
    assert scoring.check_no_junk(observed(new_facts=[{"text": "x"}], **done)).result == FAIL


def test_subagent_check_is_inconclusive_when_none_ran():
    check = scoring.check_subagent_answer(NEEDLE)
    parsed = Parsed(text="Port 7643.", subagents=0)
    assert check(Observation(turns=[turn(parsed)])).result == INCONCLUSIVE
    parsed = Parsed(text="Port 7643.", subagents=1)
    assert check(Observation(turns=[turn(parsed)])).result == PASS
    parsed = Parsed(text="Port 7643.", tool_names=["task"])
    assert check(Observation(turns=[turn(parsed)])).result == PASS


def test_git_clean_covers_setup_and_sessions_with_no_edit_task():
    clean = observed()
    assert scoring.git_is_clean(clean, no_edit=True)
    assert not scoring.git_is_clean(observed(git_after_connect=["?? AGENTS.md"]), no_edit=False)
    assert not scoring.git_is_clean(observed(head_moved=True), no_edit=False)
    edited = observed(git_after_agent=[" M calc.py"])
    assert not scoring.git_is_clean(edited, no_edit=True)
    assert scoring.git_is_clean(edited, no_edit=False)


def test_new_facts_and_status_are_read_from_records():
    records = [
        {"type": "fact", "id": "f-1"},
        {"type": "fact", "id": "f-2"},
        {"type": "change", "id": "f-1", "status": "wrong", "at": "2026-10-31T10:00:00+00:00"},
        {"type": "change", "id": "f-2", "at": "2026-10-31T10:00:00+00:00", "scope": "long"},
    ]
    assert runner.fact_states(records) == {"f-1": "wrong", "f-2": "active"}


def rows_for_report():
    common = {"agent": "claude", "tool_version": "1.2.3", "model_requested": "haiku"}
    common |= {"mode": "real", "build_version": "memory 0.3.1", "commit": "abcdef1234"}
    secret_text = "IGNORE THE TABLE | injected row"
    return [
        {
            **common,
            "build": "dev",
            "scenario": "s1",
            "result": PASS,
            "needle_in_load": True,
            "git_clean": True,
            "model_reported": "haiku-x",
            "reason": secret_text,
        },
        {
            **common,
            "build": "dev",
            "scenario": "s1",
            "result": FAIL,
            "needle_in_load": True,
            "git_clean": False,
        },
        {**common, "build": "prod", "scenario": "s1", "result": ERROR, "error_kind": "auth"},
        {
            **common,
            "build": "prod",
            "scenario": "s1",
            "result": NOT_CONNECTED,
            "needle_in_load": False,
            "git_clean": True,
        },
    ]


def test_report_shows_plain_counts_and_keeps_classes_apart():
    report = scoring.render_report(rows_for_report(), ["s1"])
    row = next(line for line in report.splitlines() if line.startswith("| s1"))
    assert "1 pass, 1 fail, n=2" in row
    assert "0 pass, 0 fail, n=2" in row
    assert "1 not-connected, 1 error" in row
    assert "2/2, 0/1" in row
    git_row = next(line for line in report.splitlines() if line.startswith("| k git-clean"))
    assert "1 pass, 1 fail, n=2" in git_row
    assert "1 pass, 0 fail, n=1" in git_row
    assert "1.2.3" in report
    assert "haiku-x" in report


def test_report_names_the_trust_step_of_the_tool():
    rows = [{**row, "connect_note": "Needs a trust review."} for row in rows_for_report()]
    assert "Needs a trust review." in scoring.render_report(rows, ["s1"])


def test_agent_text_never_reaches_the_report():
    assert "IGNORE THE TABLE" not in scoring.render_report(rows_for_report(), ["s1"])


def test_no_command_uses_a_flag_that_skips_safety_or_trust(tmp_path):
    for agent in AGENTS.values():
        for resume in (False, True):
            call = CallContext("hello", tmp_path, tmp_path, "small", resume, 0.1)
            argv = agent.argv(call)
            assert argv[0] == agent.binary
            assert forbidden_in(argv) == [], agent.name


def test_each_agent_sets_a_small_model_and_gets_the_model_flag(tmp_path):
    for agent in AGENTS.values():
        assert agent.default_model
        call = CallContext("hello", tmp_path, tmp_path, "my-model", False, None)
        assert "my-model" in agent.argv(call)


def test_fake_config_stays_in_the_temp_folder(tmp_path):
    for agent in AGENTS.values():
        if agent.fake is None:
            assert agent.no_fake_reason
            continue
        folder = tmp_path / agent.name
        folder.mkdir()
        setup = agent.fake(folder, "http://127.0.0.1:1")
        for name, value in setup.env.items():
            if value.startswith("/"):
                assert value.startswith(str(tmp_path)), name
    assert sorted(a.name for a in AGENTS.values() if a.fake is None) == ["cursor-agent"]


def post(url: str, body: dict) -> tuple[int, str]:
    request = urllib.request.Request(url, json.dumps(body).encode(), method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer sk-do-not-log")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


@pytest.mark.parametrize(
    "path,stream,marker",
    [
        ("/v1/chat/completions", False, '"content": "HELLO"'),
        ("/v1/chat/completions", True, '"content": "HELLO"'),
        ("/v1/responses", True, "response.completed"),
        ("/v1/messages", False, '"text": "HELLO"'),
        ("/v1/messages", True, "message_stop"),
    ],
)
def test_fake_provider_records_the_request_and_answers(tmp_path, path, stream, marker):
    with FakeProvider(tmp_path / "log.jsonl", reply="HELLO") as provider:
        status, text = post(provider.url + path, {"model": "m", "stream": stream, "input": "FACT"})
        rows = provider.requests()
    assert status == 200
    assert marker in text
    assert "FACT" in json.dumps(model_requests(rows))
    assert "sk-do-not-log" not in json.dumps(rows)


def test_fake_provider_can_refuse_like_an_expired_token(tmp_path):
    with FakeProvider(tmp_path / "log.jsonl", status=401) as provider:
        status, text = post(provider.url + "/v1/messages", {"model": "m"})
    assert status == 401
    assert "invalid api key" in text


class StubBuild:
    version = "memory 0.3.1"
    commit = "abc"


def options_for(tmp_path, agent="pi", scenarios=None, **kw):
    picked = scenarios or selected(["a", "h"], fake=False)
    return runner.Options(
        agent=AGENTS[agent],
        scenarios=picked,
        repeats=2,
        out_dir=tmp_path,
        builds={"dev": StubBuild(), "prod": StubBuild()},
        model="small",
        **kw,
    )


def test_plan_prints_the_cost_shape_and_names_what_it_skips(tmp_path):
    plan = runner.plan_text(options_for(tmp_path), {"dev": "HEAD", "prod": "d523c01"})
    assert "a-fact-at-start: 1 x 2 = 2" in plan
    assert "h-compaction: skipped" in plan
    assert "Cost shape: 4 agent sessions" in plan


def test_an_account_error_stops_further_calls_and_still_writes_each_row(tmp_path, monkeypatch):
    calls = []

    def fake_trial(options, build, scenario, repeat):
        calls.append((build, scenario.id, repeat))
        row = runner.base_row(options, build, scenario, repeat)
        return {**row, "result": ERROR, "reason": "401", "error_kind": "auth"}

    monkeypatch.setattr(runner, "run_trial", fake_trial)
    options = options_for(tmp_path, scenarios=selected(["a", "b"], fake=False))
    rows = runner.run_all(options)
    assert len(calls) == 1
    assert len(rows) == 8
    assert all(row["result"] == ERROR for row in rows)
    assert len(list(tmp_path.glob("*.json"))) == 8
    assert sum(row["calls"] for row in rows) == 0


LIVE_STUB = """
import json, os, sys
for line in sys.stdin:
    prompt = json.loads(line)["message"]["content"]
    if prompt == "die":
        sys.exit(3)
    print(json.dumps({"type": "assistant", "message": {"content": []}}), flush=True)
    text = f"{os.getpid()} {prompt} {os.path.exists('marker')}"
    print(json.dumps({"is_error": False, "result": text, "type": "result"}), flush=True)
"""


def stub_argv(tmp_path) -> list[str]:
    script = tmp_path / "stub.py"
    script.write_text(LIVE_STUB)
    return [sys.executable, str(script)]


def test_live_turns_keep_one_process_and_change_the_world_before_the_last_turn(tmp_path):
    turns = runner.live_turns(
        stub_argv(tmp_path),
        ("first", "second"),
        lambda: (tmp_path / "marker").write_text("x"),
        tmp_path,
        dict(os.environ),
        20,
        AGENTS["claude"].parse,
        tmp_path / "raw" / "run",
    )
    first, second = [turn.parsed.text.split() for turn in turns]
    assert first[0] == second[0], "both turns ran in one process"
    assert (first[1:], second[1:]) == (["first", "False"], ["second", "True"])
    assert all(turn.exit_code == 0 for turn in turns)
    assert (tmp_path / "raw" / "run-turn1.stdout").exists()


def test_live_turns_report_a_process_that_dies(tmp_path):
    turns = runner.live_turns(
        stub_argv(tmp_path),
        ("first", "die", "never"),
        lambda: None,
        tmp_path,
        dict(os.environ),
        20,
        AGENTS["claude"].parse,
        None,
    )
    assert len(turns) == 2
    assert turns[1].exit_code != 0
    assert not turns[1].timed_out


def test_an_unsupported_scenario_says_so(tmp_path):
    scenario = SCENARIOS["h-compaction"]
    row = runner.run_trial(options_for(tmp_path), "dev", scenario, 0)
    assert row["result"] == scoring.UNSUPPORTED
    assert "compact" in row["reason"]


def test_result_file_has_no_home_path(tmp_path):
    row = {"build": "dev", "scenario": "s", "repeat": 0, "text": f"{Path.home()}/secret"}
    path = runner.write_row(row, tmp_path)
    assert str(Path.home()) not in path.read_text()


def test_required_scenarios_exist_and_prompts_never_name_the_memory():
    letters = {scenario.id.split("-")[0] for scenario in selected(None, fake=False)}
    assert letters == {"a", "b", "c", "d", "e", "f", "g1", "g2", "h", "i", "j"}
    for scenario in SCENARIOS.values():
        for prompt in scenario.prompts:
            assert "memory" not in prompt.lower(), scenario.id


def test_fact_questions_have_a_needle_that_the_repo_files_do_not_hold():
    for scenario in SCENARIOS.values():
        if not scenario.needle or scenario.id == "i-other-branch":
            continue
        assert any(scenario.needle.search(fact.text) for fact in scenario.facts), scenario.id
        assert not any(scenario.needle.search(text) for text in scenario.files.values())


def load_cli():
    spec = importlib.util.spec_from_file_location("agent_eval_run", KIT / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_refuses_when_dev_and_prod_are_one_commit(capsys):
    assert load_cli().main(["--agent", "pi", "--dev-ref", "HEAD", "--prod-ref", "HEAD"]) == 2
    assert "same commit" in capsys.readouterr().err


def test_cli_dry_run_builds_nothing_and_spends_nothing(capsys, tmp_path):
    code = load_cli().main(["--agent", "cursor-agent", "--fake-provider", "--dry-run"])
    assert code == 0
    out = capsys.readouterr().out
    assert "not possible" in out
    assert "skipped" in out
