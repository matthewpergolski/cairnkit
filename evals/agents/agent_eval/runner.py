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
from agent_eval.agents import Agent, CallContext, FakeSetup, Parsed, live_message, version_of
from agent_eval.fake_provider import FakeProvider, model_requests
from agent_eval.sandbox import (
    Build,
    Sandbox,
    SetupError,
    make_build,
    make_sandbox,
    no_memory_build,
)
from agent_eval.scenarios import DERIVED_NOTE, Scenario

SCHEMA = 2
EXCERPT = 4000
WORK_PREFIX = "work-"


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
    agent_b: Agent | None = None
    model_b: str | None = None

    @property
    def session_b_agent(self) -> Agent:
        return self.agent_b or self.agent


@dataclass(frozen=True)
class SessionPlan:
    label: str
    agent: Agent
    model: str | None
    prompts: tuple[str, ...]


def session_plans(options: Options, scenario: Scenario) -> list[SessionPlan]:
    plans = [SessionPlan("A", options.agent, options.model, scenario.prompts)]
    if scenario.pickup:
        model = options.model_b or options.model
        plans.append(SessionPlan("B", options.session_b_agent, model, scenario.pickup))
    return plans


def unsupported_reason(
    agent: Agent, scenario: Scenario, *, fake: bool, needs: frozenset[str] | None = None
) -> str | None:
    missing = (scenario.requires if needs is None else needs) - agent.capabilities
    if missing:
        return f"{agent.name} has no headless path for: {', '.join(sorted(missing))}"
    if fake and agent.fake is None:
        return f"no fake provider path: {agent.no_fake_reason}"
    return None


def options_unsupported(options: Options, scenario: Scenario) -> str | None:
    """Why one of the tools cannot run its session of this scenario, if so."""
    reason = unsupported_reason(options.agent, scenario, fake=options.fake)
    if reason or not scenario.pickup:
        return reason
    needs = scenario.requires | scenario.requires_b
    return unsupported_reason(options.session_b_agent, scenario, fake=options.fake, needs=needs)


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
    prompts: tuple[str, ...],
    before_last,
    model: str | None,
    env: dict,
    options: Options,
    raw_prefix: Path,
) -> list[scoring.Turn]:
    turns: list[scoring.Turn] = []

    def context(prompt: str, resume: bool = False) -> CallContext:
        return CallContext(
            prompt=prompt,
            repo=box.repo,
            memory_dir=box.memory_dir if box.build.has_memory else None,
            model=model,
            resume=resume,
            budget_usd=None if options.fake else options.budget_usd,
        )

    if agent.live_argv and len(prompts) > 1:
        return live_turns(
            agent.live_argv(context("")),
            prompts,
            before_last,
            box.repo,
            env,
            options.timeout,
            agent.parse,
            raw_prefix,
        )

    for index, prompt in enumerate(prompts):
        if index == len(prompts) - 1:
            before_last()
        turn = call_one(
            agent.argv(context(prompt, index > 0)),
            box.repo,
            env,
            options.timeout,
            agent.parse,
            raw_prefix.with_name(f"{raw_prefix.name}-turn{index}"),
        )
        turns.append(turn)
        if _turn_failed(turn):
            break
    return turns


def _turn_failed(turn: scoring.Turn) -> bool:
    return turn.exit_code != 0 or turn.parsed.is_error or turn.timed_out


def run_sessions(
    box: Sandbox,
    scenario: Scenario,
    options: Options,
    raw_prefix: Path,
    provider: FakeProvider | None = None,
    fake_dir: Path | None = None,
) -> tuple[list[scoring.SessionRecord], set[str], str, list[str]]:
    """Each session in its own process, with no resume between them. Only files carry over.

    Returns the sessions, the fact ids that no session wrote, the load just before the last
    session, and where session A left the text.
    """
    known = _fact_ids(box)
    rules_words = box.rules_words()
    plans = session_plans(options, scenario)
    records: list[scoring.SessionRecord] = []
    fakes: dict[str, FakeSetup] = {}
    load_text = ""
    carried: list[str] = []

    def before_last() -> None:
        if scenario.before_last_turn and not records:
            scenario.before_last_turn(box)
            known.update(_fact_ids(box))

    for position, plan in enumerate(plans):
        if position == len(plans) - 1:
            load_text = box.load_text()
        trace_mark = len(box.build.read_trace(box.root))
        requests_mark = len(model_requests(provider.requests())) if provider else 0
        facts_mark = _fact_ids(box)
        env, model = box.env, plan.model
        if provider:
            if plan.agent.name not in fakes:
                folder = fake_dir / plan.agent.name
                folder.mkdir(parents=True)
                fakes[plan.agent.name] = plan.agent.fake(folder, provider.url)  # type: ignore[misc]
            setup = fakes[plan.agent.name]
            env, model = {**box.env, **setup.env}, setup.model
        prefix = raw_prefix.with_name(f"{raw_prefix.name}-{plan.label}")
        turns = run_turns(box, plan.agent, plan.prompts, before_last, model, env, options, prefix)
        request_text = None
        if provider:
            sent = model_requests(provider.requests())[requests_mark:]
            request_text = json.dumps(sent, ensure_ascii=False)
        records.append(
            scoring.SessionRecord(
                label=plan.label,
                agent=plan.agent.name,
                turns=turns,
                trace=box.build.read_trace(box.root)[trace_mark:],
                facts_written=len(_fact_ids(box) - facts_mark),
                probe=scenario.probe(box) if scenario.probe else {},
                request_text=request_text,
                rules_words=rules_words,
            )
        )
        if any(_turn_failed(turn) for turn in turns):
            break
        if position == 0 and scenario.pickup:
            if scenario.needle:
                new = [
                    r
                    for r in box.read_records()
                    if r.get("type") == "fact" and str(r.get("id")) not in known
                ]
                carried = box.carried_by(scenario.needle, new)
            if scenario.after_session_a:
                scenario.after_session_a(box)
                known.update(_fact_ids(box))
    return records, known, load_text, carried


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
    if scenario.pickup:
        return "two-session"
    if scenario.calls == 1:
        return "single"
    return "live" if agent.live_argv else "resume"


def base_row(options: Options, build_label: str, scenario: Scenario, repeat: int) -> dict:
    build = options.builds[build_label]
    return {
        "schema": SCHEMA,
        "agent": options.agent.name,
        "agent_a": options.agent.name,
        "agent_b": options.session_b_agent.name if scenario.pickup else None,
        "build": build_label,
        "build_version": build.version,
        "commit": build.commit,
        "scenario": scenario.id,
        "repeat": repeat,
        "mode": "fake-provider" if options.fake else "real",
        "tool_version": tool_version(options.agent),
        "tool_version_b": tool_version(options.session_b_agent) if scenario.pickup else None,
        "connect_note": options.agent.connect_note,
        "turn_mode": _turn_mode(options.agent, scenario),
        "model_requested": "fake-small" if options.fake else options.model,
        "model_requested_b": (
            ("fake-small" if options.fake else options.model_b or options.model)
            if scenario.pickup
            else None
        ),
        "model_reported": None,
        "calls": 0,
        "needle_in_load": None,
        "git_clean": None,
    }


def scored_row(
    row: dict, scenario: Scenario, obs: scoring.Observation, *, has_memory: bool = True
) -> dict:
    verdict = scoring.classify(
        obs,
        scenario.check,
        scenario.needle,
        expects_error=scenario.fake_status is not None,
        expects_connection=has_memory,
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
        git_clean=_git_clean(scenario, obs) if ran else None,
        sessions=[
            {
                "label": session.label,
                "agent": session.agent,
                "calls": len(session.turns),
                "model_reported": next(
                    (t.parsed.model for t in reversed(session.turns) if t.parsed.model), None
                ),
                "connection": scoring.session_evidence(session),
                "probe": session.probe,
                "memory_commands": scoring.memory_commands(session.trace),
                "facts_written": session.facts_written,
                "blocked_stops": scoring.blocked_stops(session.trace),
                "hook_words": scoring.injected_words(session.trace),
                "rules_words": session.rules_words,
                "request_chars": len(session.request_text or ""),
            }
            for session in obs.sessions
        ],
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


def _git_clean(scenario: Scenario, obs: scoring.Observation) -> bool:
    """A two-session scenario may ask for commits, so only its setup can read as not clean."""
    if scenario.pickup:
        return not obs.git_after_connect
    return scoring.git_is_clean(obs, scenario.no_edit)


def run_trial(options: Options, build_label: str, scenario: Scenario, repeat: int) -> dict:
    """One scenario once. A failure of the kit reads as `error`, never as a result on cairnkit."""
    agent = options.agent
    row = base_row(options, build_label, scenario, repeat)
    reason = options_unsupported(options, scenario)
    if reason:
        return {**row, "result": scoring.UNSUPPORTED, "reason": reason, "error_kind": None}
    for needed in (agent, options.session_b_agent) if scenario.pickup else (agent,):
        if not shutil.which(needed.binary):
            return {
                **row,
                "result": scoring.ERROR,
                "reason": f"{needed.binary} is not on PATH",
                "error_kind": "missing-binary",
            }

    temp = Path(tempfile.mkdtemp(prefix=WORK_PREFIX)).resolve()
    stem = f"{build_label}-{scenario.id}-{repeat}"
    try:
        box = make_sandbox(
            options.builds[build_label],
            agent,
            scenario,
            temp / "run",
            isolated_home=options.fake,
            other_agent=options.session_b_agent if scenario.pickup else None,
        )
        row["connect_steps"] = box.connect_steps
        raw_prefix = options.out_dir / "raw" / stem
        if options.fake:
            return _run_with_fake(options, box, scenario, row, temp, raw_prefix)
        return _scored_run(row, scenario, box, *run_sessions(box, scenario, options, raw_prefix))
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


def _scored_run(
    row: dict,
    scenario: Scenario,
    box: Sandbox,
    records: list[scoring.SessionRecord],
    known: set[str],
    load_text: str,
    carried: list[str],
    requests: list[dict] | None = None,
) -> dict:
    obs = read_observed(box, scenario, known)
    obs.turns = [turn for record in records for turn in record.turns]
    obs.sessions = records
    obs.has_memory = box.build.has_memory
    if scenario.needle and box.build.has_memory:
        obs.needle_in_load = bool(scenario.needle.search(load_text))
    if requests is not None:
        obs.model_requests = len(requests)
        obs.request_text = json.dumps(requests, ensure_ascii=False)
    if scenario.pickup:
        row["carried"] = carried
    return scored_row(row, scenario, obs, has_memory=box.build.has_memory)


def _run_with_fake(
    options: Options,
    box: Sandbox,
    scenario: Scenario,
    row: dict,
    temp: Path,
    raw_prefix: Path,
) -> dict:
    log_path = temp / "requests.jsonl"
    with FakeProvider(log_path, status=scenario.fake_status) as provider:
        result = run_sessions(box, scenario, options, raw_prefix, provider, temp / "fake-config")
        requests = model_requests(provider.requests())
    return _scored_run(row, scenario, box, *result, requests)


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


def arm_runs(scenario: Scenario, has_memory: bool) -> bool:
    """A scenario that asks about a planted fact says nothing in an arm with no memory."""
    return has_memory or scenario.runs_without_memory


def run_all(options: Options) -> list[dict]:
    """All trials. After an account error the tool gets no more calls: a retry only costs."""
    rows = []
    stopped: str | None = None
    for scenario in options.scenarios:
        for build_label in options.builds:
            if not arm_runs(scenario, options.builds[build_label].has_memory):
                continue
            for repeat in range(options.repeats):
                if stopped and not options_unsupported(options, scenario):
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
        f"Session A: {agent.name}",
        "Arms: " + ", ".join(f"{label} = {ref or 'no memory'}" for label, ref in refs.items()),
        f"Repeats: {options.repeats}",
    ]
    if any(scenario.pickup for scenario in options.scenarios):
        other = options.session_b_agent
        model_b = "fake-small" if options.fake else options.model_b or options.model
        lines.append(f"Session B: {other.name} ({model_b}), in a new process")
    if agent.connect_note:
        lines.append(f"Note: {agent.connect_note}")
    if options.fake and agent.fake is None:
        lines.append(f"Fake provider: not possible. {agent.no_fake_reason}")
    lines += ["", "Scenario, agent sessions per arm"]
    per_arm = dict.fromkeys(refs, 0)
    for scenario in options.scenarios:
        reason = options_unsupported(options, scenario)
        if reason:
            lines.append(f"  {scenario.id}: skipped ({reason})")
            continue
        count = scenario.calls * options.repeats
        arms = [label for label, ref in refs.items() if arm_runs(scenario, ref is not None)]
        for label in arms:
            per_arm[label] += count
        shown = ", ".join(arms)
        lines.append(f"  {scenario.id}: {scenario.calls} x {options.repeats} = {count} in {shown}")
    calls = sum(per_arm.values())
    lines += [
        "",
        f"Cost shape: {calls} agent sessions "
        f"({', '.join(f'{label} {count}' for label, count in per_arm.items())}).",
        "One agent session makes one or more model requests. The count depends on its tool use.",
    ]
    if not options.fake and agent.name == "claude" and options.budget_usd is not None:
        lines.append(
            f"Claude cap: {options.budget_usd:.2f} USD per session, "
            f"so at most {options.budget_usd * calls:.2f} USD."
        )
    lines += [
        "An account error stops the calls for this agent. The rest read as error.",
        DERIVED_NOTE,
    ]
    return "\n".join(lines) + "\n"


def load_only(options: Options) -> str:
    """What `memory load` shows for each scenario in each build. No agent runs."""
    labels = list(options.builds)
    lines = [f"| Scenario | {' | '.join(labels)} |", "|---|" + "---|" * len(labels)]
    for scenario in options.scenarios:
        if not scenario.needle:
            continue
        cells = []
        for label in labels:
            if not options.builds[label].has_memory:
                cells.append("no memory")
                continue
            temp = Path(tempfile.mkdtemp(prefix=WORK_PREFIX)).resolve()
            try:
                box = make_sandbox(
                    options.builds[label],
                    options.agent,
                    scenario,
                    temp / "run",
                    isolated_home=True,
                )
                shown = scenario.needle.search(box.load_text())
                cells.append("shown" if shown else "not shown")
            finally:
                shutil.rmtree(temp, ignore_errors=True)
        lines.append(f"| {scenario.id} | {' | '.join(cells)} |")
    return "\n".join(lines) + "\n"


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_arms(repo: Path, refs: dict[str, str | None], builds_dir: Path) -> dict[str, Build]:
    return {
        label: make_build(label, ref, repo, builds_dir) if ref else no_memory_build(builds_dir)
        for label, ref in refs.items()
    }
