"""Run one scenario once in a new repo, then write one JSON file. Also the plan and the report."""

from __future__ import annotations

import contextlib
import functools
import json
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from agent_eval import scoring
from agent_eval.agents import Agent, CallContext, Parsed, live_message, version_of
from agent_eval.fake_provider import FakeProvider, model_requests
from agent_eval.sandbox import Build, Sandbox, SetupError, make_build, make_sandbox
from agent_eval.scenarios import DERIVED_NOTE, Scenario

SCHEMA = 1
EXCERPT = 4000


@dataclass
class Options:
    agent: Agent
    scenarios: list[Scenario]
    repeats: int
    out_dir: Path
    builds: dict[str, Build] = field(default_factory=dict)
    fake: bool = False
    model: str | None = None
    timeout: float = 300
    budget_usd: float | None = 0.25
    keep: bool = False


def unsupported_reason(agent: Agent, scenario: Scenario, *, fake: bool) -> str | None:
    missing = scenario.requires - agent.capabilities
    if missing:
        return f"{agent.name} has no headless path for: {', '.join(sorted(missing))}"
    if fake and agent.fake is None:
        return f"no fake provider path: {agent.no_fake_reason}"
    return None


def call_one(
    argv: list[str], cwd: Path, env: dict, timeout: float, parse, raw_prefix: Path | None
) -> scoring.Turn:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as exc:
        return scoring.Turn(127, "", str(exc), Parsed(is_error=True, error_text=str(exc)))
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
    if raw_prefix:
        raw_prefix.parent.mkdir(parents=True, exist_ok=True)
        raw_prefix.with_suffix(".stdout").write_text(stdout, encoding="utf-8")
        raw_prefix.with_suffix(".stderr").write_text(stderr, encoding="utf-8")
    return scoring.Turn(
        exit_code=process.returncode,
        stdout=stdout,
        stderr=stderr,
        parsed=parse(stdout),
        timed_out=timed_out,
        duration_s=round(time.monotonic() - started, 1),
    )


def parse_line_type(line: str) -> str | None:
    try:
        row = json.loads(line)
    except ValueError:
        return None
    return row.get("type") if isinstance(row, dict) else None


def _read_until_result(lines: queue.Queue, deadline: float) -> tuple[list[str], bool, bool]:
    """(lines of this turn, the turn ended, the deadline passed)."""
    got: list[str] = []
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return got, False, True
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            return got, False, True
        if line is None:
            return got, False, False
        got.append(line)
        if parse_line_type(line) == "result":
            return got, True, False


def live_turns(
    argv: list[str],
    prompts: tuple[str, ...],
    before_last,
    cwd: Path,
    env: dict,
    timeout: float,
    parse,
    raw_prefix: Path | None,
) -> list[scoring.Turn]:
    """All prompts in one running process. The limit is per turn, as in `call_one`."""
    with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as stderr:
        try:
            process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                errors="replace",
                start_new_session=True,
            )
        except OSError as exc:
            return [scoring.Turn(127, "", str(exc), Parsed(is_error=True, error_text=str(exc)))]
        lines: queue.Queue = queue.Queue()

        def pump() -> None:
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        threading.Thread(target=pump, daemon=True).start()
        turns: list[scoring.Turn] = []
        for index, prompt in enumerate(prompts):
            if index == len(prompts) - 1:
                before_last()
            started = time.monotonic()
            try:
                process.stdin.write(live_message(prompt))
                process.stdin.flush()
            except (BrokenPipeError, ValueError):
                pass
            got, ended, late = _read_until_result(lines, started + timeout)
            stdout = "".join(got)
            if raw_prefix:
                path = raw_prefix.with_name(f"{raw_prefix.name}-turn{index}").with_suffix(".stdout")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(stdout, encoding="utf-8")
            parsed = parse(stdout)
            code = 0 if ended else process.poll()
            turns.append(
                scoring.Turn(
                    exit_code=1 if code is None and not late else code,
                    stdout=stdout,
                    stderr="",
                    parsed=parsed,
                    timed_out=late,
                    duration_s=round(time.monotonic() - started, 1),
                )
            )
            if not ended or parsed.is_error:
                break
        with contextlib.suppress(BrokenPipeError, OSError, ValueError):
            process.stdin.close()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        stderr.seek(0)
        if turns:
            turns[-1].stderr = stderr.read()[-4000:]
    return turns


def fact_states(records: list[dict]) -> dict[str, str]:
    """The current status of each fact: its record, then its changes in order of `at`."""
    status = {str(r.get("id")): "active" for r in records if r.get("type") == "fact"}
    changes = [r for r in records if r.get("type") == "change" and r.get("status")]
    for change in sorted(changes, key=lambda r: str(r.get("at", ""))):
        status[str(change.get("id"))] = str(change["status"])
    return status


def read_observed(box: Sandbox, scenario: Scenario, known_ids: set[str]) -> scoring.Observation:
    records = box.read_records()
    status = fact_states(records)
    new_facts = [r for r in records if r.get("type") == "fact" and r.get("id") not in known_ids]
    runs_file = box.repo / ".git" / "report-runs"
    runs = runs_file.read_text().split() if runs_file.exists() else []
    after = box.git_status()
    return scoring.Observation(
        trace=box.build.read_trace(box.root),
        new_facts=new_facts,
        fact_status=status,
        seed_ids=dict(box.seed_ids),
        git_after_connect=box.git_after_connect,
        git_before_agent=box.git_before_agent,
        git_after_agent=after,
        head_moved=box.git("rev-parse", "HEAD").strip() != box.head_after_setup,
        report_runs=runs,
        worked_file_changed=bool(
            scenario.worked_file and any(line.endswith(scenario.worked_file) for line in after)
        ),
    )


def _fact_ids(box: Sandbox) -> set[str]:
    return {str(r.get("id")) for r in box.read_records() if r.get("type") == "fact"}


def run_turns(
    box: Sandbox,
    agent: Agent,
    scenario: Scenario,
    model: str | None,
    options: Options,
    raw_prefix: Path,
) -> tuple[list[scoring.Turn], set[str]]:
    turns: list[scoring.Turn] = []
    known = _fact_ids(box)

    def context(prompt: str, resume: bool = False) -> CallContext:
        return CallContext(
            prompt=prompt,
            repo=box.repo,
            memory_dir=box.memory_dir,
            model=model,
            resume=resume,
            budget_usd=None if options.fake else options.budget_usd,
        )

    def before_last() -> None:
        if scenario.before_last_turn:
            scenario.before_last_turn(box)
            known.update(_fact_ids(box))

    if agent.live_argv and len(scenario.prompts) > 1:
        turns = live_turns(
            agent.live_argv(context("")),
            scenario.prompts,
            before_last,
            box.repo,
            box.env,
            options.timeout,
            agent.parse,
            raw_prefix,
        )
        return turns, known

    for index, prompt in enumerate(scenario.prompts):
        if index == len(scenario.prompts) - 1:
            before_last()
        turn = call_one(
            agent.argv(context(prompt, index > 0)),
            box.repo,
            box.env,
            options.timeout,
            agent.parse,
            raw_prefix.with_name(f"{raw_prefix.name}-turn{index}"),
        )
        turns.append(turn)
        if turn.exit_code != 0 or turn.parsed.is_error or turn.timed_out:
            break
    return turns, known


@functools.cache
def tool_version(agent: Agent) -> str | None:
    binary = shutil.which(agent.binary)
    if not binary:
        return None
    try:
        done = subprocess.run(
            [binary, *agent.version_args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return version_of(done.stdout or done.stderr)


def _turn_mode(agent: Agent, scenario: Scenario) -> str:
    if scenario.calls == 1:
        return "single"
    return "live" if agent.live_argv else "resume"


def base_row(options: Options, build_label: str, scenario: Scenario, repeat: int) -> dict:
    build = options.builds[build_label]
    return {
        "schema": SCHEMA,
        "agent": options.agent.name,
        "build": build_label,
        "build_version": build.version,
        "commit": build.commit,
        "scenario": scenario.id,
        "repeat": repeat,
        "mode": "fake-provider" if options.fake else "real",
        "tool_version": tool_version(options.agent),
        "connect_note": options.agent.connect_note,
        "turn_mode": _turn_mode(options.agent, scenario),
        "model_requested": "fake-small" if options.fake else options.model,
        "model_reported": None,
        "calls": 0,
        "needle_in_load": None,
        "git_clean": None,
    }


def scored_row(row: dict, scenario: Scenario, obs: scoring.Observation) -> dict:
    verdict = scoring.classify(
        obs, scenario.check, scenario.needle, expects_error=scenario.fake_status is not None
    )
    ran = verdict.result not in (scoring.ERROR, scoring.UNSUPPORTED)
    models = [turn.parsed.model for turn in obs.turns if turn.parsed.model]
    row.update(
        result=verdict.result,
        reason=verdict.reason,
        error_kind=verdict.error_kind,
        model_reported=models[-1] if models else None,
        calls=len(obs.turns),
        duration_s=round(sum(turn.duration_s for turn in obs.turns), 1),
        needle_in_load=obs.needle_in_load,
        git_clean=scoring.git_is_clean(obs, scenario.no_edit) if ran else None,
        connection={
            "evidence": scoring.connection_evidence(obs, scenario.needle),
            "hook_events": scoring.hook_events(obs.trace),
            "agent_commands": scoring.agent_commands(obs.trace),
            "delivery": scoring.delivery(obs, scenario.needle),
        },
        git={
            "after_connect": obs.git_after_connect,
            "before_agent": obs.git_before_agent,
            "after_agent": obs.git_after_agent,
            "head_moved": obs.head_moved,
        },
        new_facts=[str(fact.get("text", ""))[:400] for fact in obs.new_facts],
        model_requests=obs.model_requests,
        turns=[
            {
                "exit_code": turn.exit_code,
                "timed_out": turn.timed_out,
                "duration_s": turn.duration_s,
                "text": turn.parsed.text[:EXCERPT],
                "error_text": turn.parsed.error_text[:EXCERPT],
                "stderr_tail": turn.stderr[-1000:],
                "tool_names": turn.parsed.tool_names,
            }
            for turn in obs.turns
        ],
    )
    return row


def run_trial(options: Options, build_label: str, scenario: Scenario, repeat: int) -> dict:
    """One scenario once. A failure of the kit reads as `error`, never as a result on cairnkit."""
    agent = options.agent
    row = base_row(options, build_label, scenario, repeat)
    reason = unsupported_reason(agent, scenario, fake=options.fake)
    if reason:
        return {**row, "result": scoring.UNSUPPORTED, "reason": reason, "error_kind": None}
    if not shutil.which(agent.binary):
        return {
            **row,
            "result": scoring.ERROR,
            "reason": f"{agent.binary} is not on PATH",
            "error_kind": "missing-binary",
        }

    temp = Path(tempfile.mkdtemp(prefix="cairnkit-eval-")).resolve()
    stem = f"{build_label}-{scenario.id}-{repeat}"
    try:
        box = make_sandbox(
            options.builds[build_label],
            agent,
            scenario,
            temp / "run",
            isolated_home=options.fake,
        )
        row["connect_steps"] = box.connect_steps
        load = box.memory_cmd("load")
        needle_in_load = bool(scenario.needle and scenario.needle.search(load.stdout))
        raw_prefix = options.out_dir / "raw" / stem
        if options.fake:
            return _run_with_fake(options, box, scenario, row, needle_in_load, temp, raw_prefix)
        turns, known = run_turns(box, agent, scenario, options.model, options, raw_prefix)
        obs = read_observed(box, scenario, known)
        obs.turns = turns
        obs.needle_in_load = needle_in_load if scenario.needle else None
        return scored_row(row, scenario, obs)
    except (SetupError, RuntimeError, OSError) as exc:
        return {
            **row,
            "result": scoring.ERROR,
            "reason": f"kit setup: {exc}"[:500],
            "error_kind": "setup",
        }
    finally:
        if options.keep:
            row["kept_at"] = str(temp)
        else:
            shutil.rmtree(temp, ignore_errors=True)


def _run_with_fake(
    options: Options,
    box: Sandbox,
    scenario: Scenario,
    row: dict,
    needle_in_load: bool,
    temp: Path,
    raw_prefix: Path,
) -> dict:
    agent = options.agent
    log_path = temp / "requests.jsonl"
    with FakeProvider(log_path, status=scenario.fake_status) as provider:
        config = temp / "fake-config"
        config.mkdir()
        setup = agent.fake(config, provider.url)  # type: ignore[misc]
        box.env.update(setup.env)
        turns, known = run_turns(box, agent, scenario, setup.model, options, raw_prefix)
        requests = model_requests(provider.requests())
    obs = read_observed(box, scenario, known)
    obs.turns = turns
    obs.needle_in_load = needle_in_load if scenario.needle else None
    obs.model_requests = len(requests)
    obs.request_text = json.dumps(requests, ensure_ascii=False)
    return scored_row(row, scenario, obs)


def write_row(row: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{row['build']}-{row['scenario']}-{row['repeat']}.json"
    path = out_dir / name
    text = json.dumps(row, indent=2, ensure_ascii=False, sort_keys=True)
    path.write_text(text.replace(str(Path.home()), "~") + "\n", encoding="utf-8")
    return path


def read_rows(out_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(out_dir.glob("*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    return rows


def run_all(options: Options) -> list[dict]:
    """All trials. After an account error the tool gets no more calls: a retry only costs."""
    rows = []
    stopped: str | None = None
    for scenario in options.scenarios:
        for build_label in options.builds:
            for repeat in range(options.repeats):
                if stopped and not unsupported_reason(options.agent, scenario, fake=options.fake):
                    row = {
                        **base_row(options, build_label, scenario, repeat),
                        "result": scoring.ERROR,
                        "reason": f"not run: an earlier call ended with an {stopped} error",
                        "error_kind": stopped,
                    }
                else:
                    row = run_trial(options, build_label, scenario, repeat)
                rows.append(row)
                write_row(row, options.out_dir)
                print(_progress(row), flush=True)
                expected = scenario.fake_status is not None
                if row.get("error_kind") in scoring.ACCOUNT_ERROR_KINDS and not expected:
                    stopped = row["error_kind"]
    return rows


def _progress(row: dict) -> str:
    parts = [row["build"], row["scenario"], f"#{row['repeat']}", row["result"]]
    if row.get("error_kind"):
        parts.append(row["error_kind"])
    return " ".join(parts) + f": {row.get('reason', '')}"


def plan_text(options: Options, refs: dict[str, str]) -> str:
    """The plan and the cost shape. It spends nothing and builds nothing."""
    agent = options.agent
    lines = [
        f"Agent: {agent.name} ({agent.binary})",
        f"Mode: {'fake provider, no account, no cost' if options.fake else 'real model'}",
        f"Model: {'fake-small' if options.fake else options.model}",
        f"Builds: {', '.join(f'{label} = {ref}' for label, ref in refs.items())}",
        f"Repeats: {options.repeats}",
    ]
    if agent.connect_note:
        lines.append(f"Note: {agent.connect_note}")
    if options.fake and agent.fake is None:
        lines.append(f"Fake provider: not possible. {agent.no_fake_reason}")
    lines += ["", "Scenario, agent sessions per build"]
    total = 0
    for scenario in options.scenarios:
        reason = unsupported_reason(agent, scenario, fake=options.fake)
        if reason:
            lines.append(f"  {scenario.id}: skipped ({reason})")
            continue
        count = scenario.calls * options.repeats
        total += count
        lines.append(f"  {scenario.id}: {scenario.calls} x {options.repeats} = {count}")
    calls = total * len(refs)
    lines += [
        "",
        f"Cost shape: {calls} agent sessions ({total} per build, {len(refs)} builds).",
        "One agent session makes one or more model requests. The count depends on its tool use.",
    ]
    if not options.fake and agent.name == "claude" and options.budget_usd is not None:
        lines.append(f"Claude cap: {options.budget_usd:.2f} USD per session.")
    lines += [
        "An account error stops the calls for this agent. The rest read as error.",
        DERIVED_NOTE,
    ]
    return "\n".join(lines) + "\n"


def load_only(options: Options) -> str:
    """What `memory load` shows for each scenario in each build. No agent runs."""
    lines = ["| Scenario | dev | prod |", "|---|---|---|"]
    for scenario in options.scenarios:
        if not scenario.needle:
            continue
        cells = []
        for label in ("dev", "prod"):
            temp = Path(tempfile.mkdtemp(prefix="cairnkit-eval-")).resolve()
            try:
                box = make_sandbox(
                    options.builds[label],
                    options.agent,
                    scenario,
                    temp / "run",
                    isolated_home=True,
                )
                shown = scenario.needle.search(box.memory_cmd("load").stdout)
                cells.append("shown" if shown else "not shown")
            finally:
                shutil.rmtree(temp, ignore_errors=True)
        lines.append(f"| {scenario.id} | {cells[0]} | {cells[1]} |")
    return "\n".join(lines) + "\n"


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_both(repo: Path, refs: dict[str, str], builds_dir: Path) -> dict[str, Build]:
    return {label: make_build(label, ref, repo, builds_dir) for label, ref in refs.items()}
