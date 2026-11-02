"""Turn what one run left behind into one result class. Pure: no process, no network.

Agent output is data. It is matched against fixed patterns and never run or formatted as a
command. The report table holds only counts, so agent text cannot reach it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from agent_eval.agents import Parsed

PASS = "pass"
FAIL = "fail"
NOT_CONNECTED = "not-connected"
ERROR = "error"
UNSUPPORTED = "unsupported"
INCONCLUSIVE = "inconclusive"
RESULT_CLASSES = (PASS, FAIL, NOT_CONNECTED, ERROR, UNSUPPORTED, INCONCLUSIVE)
NO_MEMORY = "none"

ACCOUNT_ERROR_KINDS = frozenset({"auth", "quota"})

_TRUST = re.compile(
    r"workspace trust|not trusted|untrusted (?:folder|project|workspace)|trust this (?:folder|"
    r"project|workspace)|needs? to be trusted|requires? trust|--trust\b",
    re.I,
)
_AUTH = re.compile(
    r"\b401\b|\b403\b|unauthori[sz]ed|forbidden|invalid[ _]api[ _]key|api key|authenticat|"
    r"not (?:signed|logged) in|/login|login required|sign in|(?:token|session|credentials?)"
    r"[^.\n]{0,40}expired|expired[^.\n]{0,20}(?:token|session|credentials?)|oauth",
    re.I,
)
_QUOTA = re.compile(
    r"\b429\b|rate.?limit|quota|insufficient|credit balance|usage limit|max_budget|out of credits|"
    r"billing",
    re.I,
)
_SHORT_ACCOUNT = re.compile(
    r"^\W*(?:invalid api key|not logged in|not signed in|please run /login|"
    r"oauth token (?:has )?expired|authentication (?:failed|error)|credit balance)",
    re.I,
)
_RULES_TEXT = re.compile(r"\bmemory (?:add|search|load)\b")
_LOOKUP_COMMANDS = {"load", "search", "show"}
_WRITE_COMMANDS = {"add", "change", "keep"}
_HOOK_START = "session-start"


@dataclass
class Turn:
    exit_code: int | None
    stdout: str
    stderr: str
    parsed: Parsed
    timed_out: bool = False
    duration_s: float = 0.0


@dataclass
class SessionRecord:
    """One process of the agent tool, and what the run looked like when it ended."""

    label: str
    agent: str
    turns: list[Turn] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    facts_written: int = 0
    probe: dict = field(default_factory=dict)
    request_text: str | None = None


@dataclass
class Observation:
    """What a script can read after a run: output, memory files, git and the tool trace."""

    turns: list[Turn] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)
    new_facts: list[dict] = field(default_factory=list)
    fact_status: dict[str, str] = field(default_factory=dict)
    seed_ids: dict[str, str] = field(default_factory=dict)
    needle_in_load: bool | None = None
    git_after_connect: list[str] = field(default_factory=list)
    git_before_agent: list[str] = field(default_factory=list)
    git_after_agent: list[str] = field(default_factory=list)
    head_moved: bool = False
    request_text: str | None = None
    model_requests: int | None = None
    report_runs: list[str] = field(default_factory=list)
    worked_file_changed: bool = False
    sessions: list[SessionRecord] = field(default_factory=list)
    has_memory: bool = True

    @property
    def final_text(self) -> str:
        return self.turns[-1].parsed.text if self.turns else ""

    @property
    def tool_names(self) -> list[str]:
        return [name for turn in self.turns for name in turn.parsed.tool_names]


@dataclass(frozen=True)
class Outcome:
    result: str
    reason: str


@dataclass(frozen=True)
class Verdict:
    result: str
    reason: str
    error_kind: str | None = None


def _commands(trace: Iterable[dict]) -> list[list[str]]:
    return [[str(word) for word in row.get("argv", [])] for row in trace]


def hook_events(trace: Iterable[dict]) -> list[str]:
    """The hook events that really ran, for example `session-start` and `stop`."""
    events = []
    for argv in _commands(trace):
        if "hook" in argv:
            index = argv.index("hook")
            if index + 1 < len(argv):
                events.append(argv[index + 1])
    return events


def agent_commands(trace: Iterable[dict]) -> list[str]:
    """The `memory` subcommands that ran outside a hook."""
    found = []
    for argv in _commands(trace):
        if "hook" in argv:
            continue
        words = [word for word in argv if word in _LOOKUP_COMMANDS | _WRITE_COMMANDS]
        if words:
            found.append(words[0])
    return found


def connection_evidence(obs: Observation, needle: re.Pattern | None) -> list[str]:
    """Each thing that shows the tool reached this run. Empty means not connected."""
    evidence = []
    if _HOOK_START in hook_events(obs.trace):
        evidence.append("session-start-hook")
    commands = agent_commands(obs.trace)
    if any(command in _LOOKUP_COMMANDS for command in commands):
        evidence.append("agent-ran-lookup")
    if any(command in _WRITE_COMMANDS for command in commands):
        evidence.append("agent-ran-write")
    if needle and needle.search(obs.final_text):
        evidence.append("fact-in-answer")
    shown = delivery(obs, needle)
    if shown == "fact":
        evidence.append("fact-in-request")
    elif shown == "rules":
        evidence.append("rules-in-request")
    return evidence


def delivery(obs: Observation, needle: re.Pattern | None) -> str | None:
    """With the fake provider: what reached the model. None without a request log."""
    if obs.request_text is None:
        return None
    if needle and needle.search(obs.request_text):
        return "fact"
    if _RULES_TEXT.search(obs.request_text):
        return "rules"
    return "none"


def session_evidence(session: SessionRecord) -> list[str]:
    """The same evidence for one session. An answer counts for nothing here: git can carry it."""
    return connection_evidence(
        Observation(trace=session.trace, request_text=session.request_text), None
    )


def _unconnected(obs: Observation, needle: re.Pattern | None) -> str | None:
    if len(obs.sessions) > 1:
        lost = [s.label for s in obs.sessions if not session_evidence(s)]
        if lost:
            return f"session {', '.join(lost)}: no hook ran and no memory command ran"
        return None
    if connection_evidence(obs, needle):
        return None
    return "no hook ran, no memory command ran, and no fact showed"


def _failed_turns(obs: Observation) -> list[Turn]:
    return [turn for turn in obs.turns if turn.exit_code != 0 or turn.parsed.is_error]


def _error_blob(turn: Turn) -> str:
    # stdout counts only through the parsed error text: a model may say "401" in a good answer.
    if turn.parsed.is_error:
        return f"{turn.parsed.error_text}\n{turn.stderr}"
    return f"{turn.stderr}\n{turn.stdout[-2000:] if not turn.parsed.text else ''}"


def _refusal(text: str) -> tuple[str, str] | None:
    if _QUOTA.search(text):
        return ("quota", "the provider refused: rate limit, quota or budget")
    if _AUTH.search(text):
        return ("auth", "the account or token was refused")
    return None


def detect_trust_block(obs: Observation) -> str | None:
    for turn in _failed_turns(obs):
        if _TRUST.search(_error_blob(turn)):
            return "a trust step stopped the run"
    return None


def detect_error(obs: Observation) -> tuple[str, str] | None:
    """(kind, reason) for a run that says nothing about cairnkit."""
    if not obs.turns:
        return ("no-run", "no turn ran")
    for turn in obs.turns:
        if turn.timed_out:
            # A tool can spend the whole limit on retries of a refused token.
            return _refusal(turn.parsed.retry_error) or (
                "timeout",
                "the agent passed the time limit",
            )
    for turn in _failed_turns(obs):
        blob = _error_blob(turn)
        return _refusal(blob) or ("crash", f"the tool exited {turn.exit_code} with an error")
    for turn in obs.turns:
        text = turn.parsed.text.strip()
        if len(text) < 200 and _SHORT_ACCOUNT.search(text):
            return ("auth", "the tool answered with an account message")
    if not obs.turns[-1].parsed.text.strip():
        return ("empty-output", "the tool gave no answer text")
    return None


def classify(
    obs: Observation,
    check: Callable[[Observation], Outcome],
    needle: re.Pattern | None,
    *,
    expects_error: bool = False,
    expects_connection: bool = True,
) -> Verdict:
    """The one place that orders the classes. A trust stop and an account error come first."""
    trust = detect_trust_block(obs)
    if trust:
        return Verdict(NOT_CONNECTED, trust)
    error = detect_error(obs)
    if error:
        kind, reason = error
        return Verdict(ERROR, reason, kind)
    if expects_error:
        return Verdict(FAIL, "a provider refusal did not read as an error")
    unconnected = _unconnected(obs, needle) if expects_connection else None
    if unconnected:
        return Verdict(NOT_CONNECTED, unconnected)
    outcome = check(obs)
    return Verdict(outcome.result, outcome.reason)


def check_answer_has(needle: re.Pattern) -> Callable[[Observation], Outcome]:
    def check(obs: Observation) -> Outcome:
        if needle.search(obs.final_text):
            return Outcome(PASS, "the answer holds the stored fact")
        return Outcome(FAIL, "the answer does not hold the stored fact")

    return check


def check_fact_reached_model(needle: re.Pattern) -> Callable[[Observation], Outcome]:
    def check(obs: Observation) -> Outcome:
        shown = delivery(obs, needle)
        if shown == "fact":
            return Outcome(PASS, "the fact text is in a model request")
        if shown == "rules":
            return Outcome(NOT_CONNECTED, "only the rules reached the model, not the fact")
        return Outcome(NOT_CONNECTED, "no memory text reached the model")

    return check


def check_fact_corrected(wrong_text: str) -> Callable[[Observation], Outcome]:
    def check(obs: Observation) -> Outcome:
        fact_id = obs.seed_ids.get(wrong_text)
        status = obs.fact_status.get(fact_id or "", "active")
        if status != "active":
            return Outcome(PASS, f"the wrong trap is now {status}")
        return Outcome(FAIL, "the wrong trap is still active after the evidence")

    return check


def check_wrote_useful_fact(needle: re.Pattern) -> Callable[[Observation], Outcome]:
    def check(obs: Observation) -> Outcome:
        fails = obs.report_runs.count("fail")
        if fails < 2 or not obs.report_runs or obs.report_runs[-1] != "pass":
            return Outcome(INCONCLUSIVE, "the run did not repeat a failure and then pass")
        if any(needle.search(str(fact.get("text", ""))) for fact in obs.new_facts):
            return Outcome(PASS, "a new fact names the fix")
        return Outcome(FAIL, f"{len(obs.new_facts)} new fact(s), none names the fix")

    return check


def check_captured(needle: re.Pattern) -> Callable[[Observation], Outcome]:
    def check(obs: Observation) -> Outcome:
        if any(needle.search(str(fact.get("text", ""))) for fact in obs.new_facts):
            return Outcome(PASS, "a new fact holds the correction")
        return Outcome(FAIL, f"{len(obs.new_facts)} new fact(s), none holds the correction")

    return check


def check_no_junk(obs: Observation) -> Outcome:
    if not obs.worked_file_changed:
        return Outcome(INCONCLUSIVE, "the routine work was not done")
    if obs.new_facts:
        return Outcome(FAIL, f"{len(obs.new_facts)} fact(s) written for routine work")
    return Outcome(PASS, "no fact written for routine work")


def check_subagent_answer(needle: re.Pattern) -> Callable[[Observation], Outcome]:
    def check(obs: Observation) -> Outcome:
        counted = [turn.parsed.subagents for turn in obs.turns if turn.parsed.subagents is not None]
        spawned = (
            sum(counted) > 0
            if counted
            else any(re.search(r"task|agent|collab", name, re.I) for name in obs.tool_names)
        )
        if not spawned:
            return Outcome(INCONCLUSIVE, "no subagent ran")
        if needle.search(obs.final_text):
            return Outcome(PASS, "the subagent's answer holds the stored fact")
        return Outcome(FAIL, "a subagent ran and the answer does not hold the stored fact")

    return check


def check_after_compaction(needle: re.Pattern) -> Callable[[Observation], Outcome]:
    def check(obs: Observation) -> Outcome:
        if not needle.search(obs.final_text):
            return Outcome(FAIL, "after the compaction the answer lost the stored fact")
        return Outcome(PASS, "after the compaction the answer holds the stored fact")

    return check


_WAITING_LINE = re.compile(r"WAITING:\**\s*(.*)", re.I)


def check_waiting(settled: str, still_open: str) -> Callable[[Observation], Outcome]:
    """The last WAITING line decides. It must name the open item, so silence never passes."""

    def check(obs: Observation) -> Outcome:
        lines = _WAITING_LINE.findall(obs.final_text)
        if not lines:
            return Outcome(INCONCLUSIVE, "the answer has no WAITING line")
        numbers = re.findall(r"\d+", lines[-1])
        if settled in numbers:
            return Outcome(FAIL, f"it reports #{settled} as waiting after the owner decided it")
        if still_open not in numbers:
            return Outcome(INCONCLUSIVE, f"it does not name #{still_open}, which is still open")
        return Outcome(PASS, f"it names #{still_open} and not #{settled}")

    return check


def _probes(obs: Observation) -> tuple[dict, dict]:
    if len(obs.sessions) < 2:
        return {}, {}
    return obs.sessions[0].probe, obs.sessions[1].probe


def check_answer_after_work(needle: re.Pattern) -> Callable[[Observation], Outcome]:
    """Session B states the text, and session A did the branch work that the text is about."""

    def check(obs: Observation) -> Outcome:
        if not _probes(obs)[0].get("branch_commits"):
            return Outcome(INCONCLUSIVE, "session A made no commit on the branch")
        if needle.search(obs.final_text):
            return Outcome(PASS, "session B states what only the conversation of session A held")
        return Outcome(FAIL, "session B does not state what session A was told")

    return check


def check_worktree_untouched(obs: Observation) -> Outcome:
    probe = _probes(obs)[1]
    if not probe.get("wip_intact"):
        return Outcome(FAIL, "the edits of the running work changed, or a commit took them")
    if not probe.get("tidied"):
        return Outcome(INCONCLUSIVE, "session B tidied nothing, so its care shows nothing")
    return Outcome(PASS, "session B tidied, and the edits of the running work are as they were")


def check_lesson(obs: Observation) -> Outcome:
    before, after = _probes(obs)
    first = before.get("runs", [])
    runs = after.get("runs", [])[len(first) :]
    if "fail" not in first or not first or first[-1] != "pass":
        return Outcome(INCONCLUSIVE, "session A did not hit the failure and fix it")
    if not runs:
        return Outcome(INCONCLUSIVE, "session B did not run the command")
    if runs[0] == "fail":
        return Outcome(FAIL, "the first run of session B repeats the failure")
    return Outcome(PASS, "the first run of session B passes")


_ATTEMPTS = re.compile(r"^MAX_ATTEMPTS\s*=\s*(\d+)\s*$", re.M)
_BACKOFF = re.compile(r"^BACKOFF_SECONDS\s*=\s*(\d+)\s*$", re.M)


def check_promise(limit: int, outage_seconds: int, original_send: str):
    """A check on the file: the limit holds, and the outage task was really done."""

    def check(obs: Observation) -> Outcome:
        probe = _probes(obs)[1]
        attempts = _ATTEMPTS.search(probe.get("config", ""))
        backoff = _BACKOFF.search(probe.get("config", ""))
        if not attempts or not backoff:
            return Outcome(INCONCLUSIVE, "the settings file has another form now")
        count, wait = int(attempts[1]), int(backoff[1])
        if count > limit:
            return Outcome(FAIL, f"MAX_ATTEMPTS is {count}, and the promise says {limit}")
        send = probe.get("send", "")
        if send != original_send:
            if "range(MAX_ATTEMPTS)" not in send:
                return Outcome(INCONCLUSIVE, "the send loop no longer reads the limit")
            return Outcome(PASS, f"MAX_ATTEMPTS is {count}, and the send loop still reads it")
        if count * wait < outage_seconds:
            return Outcome(INCONCLUSIVE, "the promise holds, but the outage task was not done")
        return Outcome(PASS, f"MAX_ATTEMPTS is {count}, and the backoff covers the outage")

    return check


def check_channel(needle: re.Pattern) -> Callable[[Observation], Outcome]:
    """Fake provider: what session A left reaches session B, and the none arm gets no text."""

    def check(obs: Observation) -> Outcome:
        text = obs.sessions[-1].request_text or ""
        if text in ("", "[]"):
            return Outcome(INCONCLUSIVE, "session B sent no request to the model")
        if obs.has_memory:
            if needle.search(text):
                return Outcome(PASS, "the fact of session A is in a request of session B")
            return Outcome(NOT_CONNECTED, "the fact of session A did not reach session B")
        if needle.search(text) or _RULES_TEXT.search(text):
            return Outcome(FAIL, "the arm with no memory sent memory text to the model")
        return Outcome(PASS, "no memory text in a request of the arm with no memory")

    return check


def git_is_clean(obs: Observation, no_edit: bool) -> bool:
    """Item (k): setup leaves git clean, and a session with no edit task changes nothing."""
    if obs.git_after_connect or obs.head_moved:
        return False
    return not no_edit or obs.git_after_agent == obs.git_before_agent


def summarize(rows: list[dict]) -> dict[tuple[str, str], dict[str, int]]:
    """Counts per (scenario, build). `n` is the number of runs that the row holds."""
    table: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        cell = table.setdefault(
            (row["scenario"], row["build"]),
            {**{name: 0 for name in RESULT_CLASSES}, "n": 0, "in_load": 0, "load_known": 0},
        )
        cell[row["result"]] += 1
        cell["n"] += 1
        if row.get("needle_in_load") is not None:
            cell["load_known"] += 1
            cell["in_load"] += int(bool(row["needle_in_load"]))
    return table


def _other(cell: dict[str, int] | None) -> str:
    if not cell:
        return "-"
    shown = [f"{cell[name]} {name}" for name in (NOT_CONNECTED, ERROR, UNSUPPORTED, INCONCLUSIVE)]
    return ", ".join(part for part in shown if not part.startswith("0 ")) or "-"


def _score(cell: dict[str, int] | None) -> str:
    if not cell:
        return "-"
    return f"{cell[PASS]} pass, {cell[FAIL]} fail, n={cell['n']}"


def _load(cell: dict[str, int] | None) -> str:
    if not cell or not cell["load_known"]:
        return "-"
    return f"{cell['in_load']}/{cell['load_known']}"


def arm_order(rows: list[dict]) -> list[str]:
    """The first arms first, the arms added later next, and the no-memory arm as the last."""
    found = {row["build"] for row in rows}
    first = [arm for arm in ("dev", "prod") if arm in found]
    last = [NO_MEMORY] if NO_MEMORY in found else []
    return first + sorted(found - {"dev", "prod", NO_MEMORY}) + last


def _git_row(rows: list[dict], arms: list[str]) -> str | None:
    counted = [row for row in rows if row.get("git_clean") is not None]
    if not counted:
        return None
    cells = []
    for build in arms:
        mine = [row for row in counted if row["build"] == build]
        clean = sum(1 for row in mine if row["git_clean"])
        dirty = len(mine) - clean
        cells.append(f"{clean} pass, {dirty} fail, n={len(mine)}" if mine else "-")
    blanks = " | ".join("-" for _ in arms)
    return f"| k git-clean (all runs) | {' | '.join(cells)} | {blanks} | - | - |"


def render_report(rows: list[dict], order: list[str] | None = None) -> str:
    """A short Markdown table: the arms side by side per scenario, with plain counts."""
    if not rows:
        return "No results.\n"
    head = rows[0]
    table = summarize(rows)
    arms = arm_order(rows)
    scenarios = order or sorted({row["scenario"] for row in rows})
    seen = sorted({row["model_reported"] for row in rows if row.get("model_reported")})
    lines = [
        f"# {head['agent']}: {' against '.join(arms)}",
        "",
        f"- Tool version: {head.get('tool_version') or 'unknown'}",
        f"- Model asked: {head.get('model_requested') or 'default'}. "
        f"Model seen: {', '.join(seen) or 'unknown'}.",
        f"- Mode: {head.get('mode')}",
        "- " + " ".join(f"{arm}: {_build_label(rows, arm)}." for arm in arms),
    ]
    if head.get("connect_note"):
        lines.append(f"- Connection: {head['connect_note']}")
    lines += [
        "",
        "`n` counts the runs. With a small `n`, one run moves a rate far, so read counts, not "
        "rates. `In load` counts the runs where `memory load` showed the fact before the agent "
        "started, so it separates 'could not see it' from 'saw it and did not act'.",
        "",
        "| Scenario | "
        + " | ".join(arms + [f"{arm} other" for arm in arms])
        + f" | In load {', '.join(arms)} | Tools A, B |",
        "|---|" + "---|" * (2 * len(arms) + 2),
    ]
    for scenario in scenarios:
        cells = [table.get((scenario, arm)) for arm in arms]
        if not any(cells):
            continue
        shown = [_score(cell) for cell in cells] + [_other(cell) for cell in cells]
        load = ", ".join(_load(cell) for cell in cells)
        tools = _tools_cell(rows, scenario)
        lines.append(f"| {scenario} | {' | '.join(shown)} | {load} | {tools} |")
    git_row = _git_row(rows, arms)
    if git_row:
        lines.append(git_row)
    return "\n".join(lines + _carried_table(rows, scenarios, arms)) + "\n"


def _tools_cell(rows: list[dict], scenario: str) -> str:
    pairs = {
        (row.get("agent_a") or row.get("agent"), row.get("agent_b"))
        for row in rows
        if row["scenario"] == scenario
    }
    return "; ".join(sorted(f"{a}, {b}" if b else str(a) for a, b in pairs))


def _carried_table(rows: list[dict], scenarios: list[str], arms: list[str]) -> list[str]:
    """Where session A left what session B needs. Word match, so read it as a hint."""
    mine = [row for row in rows if "carried" in row]
    if not mine:
        return []
    lines = [
        "",
        "Where session A left the text, counted over the runs that ran (word match):",
        "",
        f"| Scenario | {' | '.join(arms)} |",
        "|---|" + "---|" * len(arms),
    ]
    for scenario in scenarios:
        cells = []
        for arm in arms:
            runs = [r for r in mine if r["scenario"] == scenario and r["build"] == arm]
            counts = {c: sum(c in r["carried"] for r in runs) for c in ("memory", "git", "file")}
            cells.append(", ".join(f"{k} {v}" for k, v in counts.items()) + f" of {len(runs)}")
        if any(row["scenario"] == scenario for row in mine):
            lines.append(f"| {scenario} | {' | '.join(cells)} |")
    return lines


def _build_label(rows: list[dict], build: str) -> str:
    if build == NO_MEMORY:
        return "no memory, no hooks, no rules"
    for row in rows:
        if row["build"] == build:
            return f"{row.get('build_version') or '?'} at {str(row.get('commit') or '?')[:7]}"
    return "not run"
