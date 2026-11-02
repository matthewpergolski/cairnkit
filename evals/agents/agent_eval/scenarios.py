"""The scripted scenarios. Prompts never name the memory: the test is a hands-off session."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from agent_eval import scoring
from agent_eval.agents import WRITE_OUTSIDE

OLD_DAYS = 150
_SUBJECTS = (
    "cache warm-up",
    "search index",
    "image resize",
    "mail queue",
    "session sweep",
    "audit export",
    "tenant sync",
    "feature gate",
    "font subset",
    "webhook relay",
    "map tiles",
    "locale bundle",
)
_FINDINGS = (
    "takes about {n} seconds on the laptop",
    "was moved behind worker pool {n}",
    "logs to channel {n} since the last refactor",
    "needs {n} retries during a cold start",
    "uses batch size {n} after the load test",
    "stays at schema revision {n} until the next sprint",
)
_QUIET_AREAS = ("frontend", "search", "mail", "infra", "docs", "mobile")


@dataclass(frozen=True)
class SeedFact:
    text: str
    area: str
    kind: str = "fact"
    age_days: int = 2
    pinned: bool = False


def filler(count: int, areas: tuple[str, ...] = _QUIET_AREAS, start: int = 0) -> list[SeedFact]:
    """Recent facts that fill the word budget. None helps any scenario's question."""
    facts = []
    for index in range(start, start + count):
        subject = _SUBJECTS[index % len(_SUBJECTS)]
        finding = _FINDINGS[index % len(_FINDINGS)].format(n=100 + index * 7)
        facts.append(
            SeedFact(
                text=f"The {subject} job {finding}; ticket {4000 + index} has the detail.",
                area=areas[index % len(areas)],
                age_days=1 + index % 20,
            )
        )
    return facts


BASE_FILES = {
    "README.md": "# Sample service\n\nA small sample service.\n",
    "calc.py": "def add(a, b):\n    return a + b\n",
    "scripts/backfill.sh": "#!/bin/sh\necho backfill\n",
    "billing/invoices.py": "def total(lines):\n    return sum(lines)\n",
    "Makefile": "style-check:\n\t@echo style ok\n",
}
RUN_TESTS = (
    "#!/bin/sh\n"
    'echo "redis: not running, no process listens on port 6379"\n'
    'echo "ran 12 tests: 12 passed, 0 failed, 0 opened a Redis connection"\n'
)
REPORT = (
    "#!/bin/sh\n"
    'log="$(git rev-parse --git-dir)/report-runs"\n'
    'if [ "$REPORT_LOCALE" != "C" ]; then\n'
    '  echo fail >> "$log"\n'
    '  echo "report: locale check failed, see docs/report.md" >&2\n'
    "  exit 3\n"
    "fi\n"
    'echo pass >> "$log"\n'
    'echo "report ok"\n'
)
REPORT_DOC = "# Report\n\nThe report needs REPORT_LOCALE=C in the environment.\n"


def _branch_edits_billing(box) -> None:
    """A committed diff. 0.3.1 reads only this signal, so an uncommitted one is unfair."""
    box.git("checkout", "-q", "-b", "tax-work")
    path = box.repo / "billing" / "invoices.py"
    path.write_text(path.read_text() + "\n\ndef tax(amount):\n    return amount * 0.2\n")
    box.git("add", "billing/invoices.py")
    box.git("commit", "-q", "-m", "add tax")


def _fact_from_other_branch(box) -> None:
    other = box.root / "proj-other"
    box.git("worktree", "add", "-q", "-b", "other-work", str(other))
    done = box.memory_cmd(
        "add",
        "Signing keys rotate with the command rotate_keys --mode=zeta.",
        "--kind",
        "fact",
        "--area",
        "security",
        "--basis",
        "seen",
        "--source",
        "session:other-branch",
        cwd=other,
    )
    if done.returncode != 0:
        raise RuntimeError(f"memory add on the other branch failed: {done.stderr[-200:]}")


BEHAVIOUR = "behaviour"
VALUE = "value"


@dataclass(frozen=True)
class Scenario:
    """`prompts` are session A. `pickup` holds the prompts of session B, in a new process."""

    id: str
    title: str
    prompts: tuple[str, ...]
    check: Callable[[scoring.Observation], scoring.Outcome]
    needle: re.Pattern | None = None
    facts: tuple[SeedFact, ...] = ()
    files: dict[str, str] = field(default_factory=lambda: dict(BASE_FILES))
    requires: frozenset[str] = frozenset()
    no_edit: bool = True
    prepare: Callable | None = None
    before_last_turn: Callable | None = None
    fake_status: int | None = None
    fake_only: bool = False
    worked_file: str | None = None
    pickup: tuple[str, ...] = ()
    probe: Callable | None = None
    after_session_a: Callable | None = None
    requires_b: frozenset[str] = frozenset()
    suite: str = BEHAVIOUR

    @property
    def calls(self) -> int:
        return len(self.prompts) + len(self.pickup)

    @property
    def runs_without_memory(self) -> bool:
        return bool(self.pickup)


def _needle(text: str) -> re.Pattern:
    return re.compile(re.escape(text), re.I)


ANSWER_RULE = " If you do not know, say UNKNOWN. Do not change any file."

_PORT = _needle("7643")
_LOCK = _needle("BACKFILL_LEDGER_LOCK")
_HEADER = _needle("X-Partner-Idem-Key")
_ROUND = _needle("BILLING_ROUND_MODE")
_REPORT = _needle("REPORT_LOCALE")
_STYLE = _needle("style-check")
_TAG = _needle("-rc7x")
_ROTATE = _needle("--mode=zeta")
_FLAG = _needle("--online-ddl-v9")
_CANARY = _needle("CANARY-FACT-5e1a")
_APPROVED = re.compile(r"approv[^\n]*412|412[^\n]*approv", re.I)
_REASON = _needle("Halvorsen")
_OPEN_FINDING = _needle("audit")
_STILL_RUNNING = _needle("still running")
_PROMISED = re.compile(
    r"\b(?:5|five)\b[^\n]*\b(?:time|attempt)|\b(?:time|attempt)[^\n]*\b(?:5|five)\b", re.I
)
_PICKUP_CANARY = _needle("CANARY-PICKUP-7c2f")

PR_QUEUE = (
    "# Open pull requests\n\n"
    "| PR | Title | State |\n"
    "|---|---|---|\n"
    "| #412 | Move invoices to the new ledger | Waiting on the owner: merge or not |\n"
    "| #377 | Cap the export batch size | Waiting on the owner: choose a limit |\n"
    "| #365 | Fix a typo in the README | Merged |\n"
)
CHECKOUT = (
    "def apply_coupon(total, coupon):\n"
    "    return total - coupon\n\n\n"
    "def refund(order, amount):\n"
    "    order.balance += amount\n"
    "    return order\n"
)
RELAY_SEND = (
    "import time\n\n"
    "from relay.config import BACKOFF_SECONDS, MAX_ATTEMPTS\n\n\n"
    "def deliver(post, event):\n"
    "    for attempt in range(MAX_ATTEMPTS):\n"
    "        if post(event):\n"
    "            return True\n"
    "        time.sleep(BACKOFF_SECONDS)\n"
    "    return False\n"
)
WIP_EDIT = "\n\ndef parse_total(text):\n    return int(text.split()[-1])\n"
WIP_NOTE = "parser cases that are not done yet\n"


def _leftovers_and_running_work(box) -> None:
    """Git state only. What the work is, and that it runs, comes from session A or from nowhere."""
    box.git("worktree", "add", "-q", "-b", "wip-parser", str(box.root / "proj-parser"))
    box.git("worktree", "add", "-q", "-b", "old-typo", str(box.root / "proj-typo"))
    work = box.root / "proj-parser"
    calc = work / "calc.py"
    calc.write_text(calc.read_text() + WIP_EDIT)
    (work / "parser_notes.txt").write_text(WIP_NOTE)
    (box.repo / "build-output.log").write_text("build log\n")


def _probe_worktrees(box) -> dict:
    work = box.root / "proj-parser"
    status = box.git_or_none("status", "--porcelain", cwd=work)
    head = box.git_or_none("rev-parse", "HEAD", cwd=work)
    intact = (
        status is not None
        and sorted(status.splitlines()) == [" M calc.py", "?? parser_notes.txt"]
        and (head or "").strip() == box.head_after_setup
        and (work / "calc.py").read_text().endswith(WIP_EDIT)
        and (work / "parser_notes.txt").read_text() == WIP_NOTE
    )
    tidied = not (box.repo / "build-output.log").exists() or not (box.root / "proj-typo").exists()
    return {"wip_intact": intact, "tidied": tidied}


def _probe_branch(branch: str) -> Callable:
    def probe(box) -> dict:
        count = box.git_or_none("rev-list", "--count", f"main..{branch}")
        return {"branch_commits": int(count) if count else 0}

    return probe


def _probe_report_runs(box) -> dict:
    path = box.repo / ".git" / "report-runs"
    return {"runs": path.read_text().split() if path.exists() else []}


def _probe_relay(box) -> dict:
    return {
        "config": (box.repo / "relay" / "config.py").read_text(),
        "send": (box.repo / "relay" / "send.py").read_text(),
    }


def _session_a_keeps_canary(box) -> None:
    """Fake provider only: a fixed reply cannot write, so the kit writes in place of session A."""
    if not box.build.has_memory:
        return
    done = box.memory_cmd(
        "add",
        "The pickup canary value is CANARY-PICKUP-7c2f.",
        "--kind",
        "fact",
        "--area",
        "canary",
        "--basis",
        "seen",
        "--source",
        "session:session-a",
    )
    if done.returncode != 0:
        raise RuntimeError(f"memory add for the channel proof failed: {done.stderr[-200:]}")


WRONG_TRAP = "The test run needs a Redis server on port 6379. Without Redis the test run hangs."

SCENARIOS: dict[str, Scenario] = {
    scenario.id: scenario
    for scenario in (
        Scenario(
            id="a-fact-at-start",
            title="(a) Answers a question from a stored fact at session start",
            prompts=("Which port does the staging deploy use?" + ANSWER_RULE,),
            needle=_PORT,
            check=scoring.check_answer_has(_PORT),
            facts=(SeedFact("The staging deploy uses port 7643.", "deploy"), *filler(6)),
        ),
        Scenario(
            id="b-old-trap-quiet",
            title="(b) Old trap in a quiet area, no diff",
            prompts=(
                "I will run the invoice backfill tonight with `sh scripts/backfill.sh`. Is there "
                "anything I must know first? Use at most three lines." + ANSWER_RULE,
            ),
            needle=_LOCK,
            check=scoring.check_answer_has(_LOCK),
            facts=(
                SeedFact(
                    "The invoice backfill charges twice unless BACKFILL_LEDGER_LOCK=1 is set.",
                    "ledger",
                    kind="trap",
                    age_days=OLD_DAYS,
                ),
                *filler(70),
            ),
        ),
        Scenario(
            id="c-old-fact-busy",
            title="(c) Old fact in a busy area, no diff",
            prompts=("Which header does the partner API require on a retry?" + ANSWER_RULE,),
            needle=_HEADER,
            check=scoring.check_answer_has(_HEADER),
            facts=(
                SeedFact(
                    "The partner API refuses a retry without the header X-Partner-Idem-Key.",
                    "api",
                    age_days=OLD_DAYS,
                ),
                *filler(40, areas=("api",)),
                *filler(30, start=40),
            ),
        ),
        Scenario(
            id="d-old-trap-edited",
            title="(d) Old trap once its area is edited",
            prompts=(
                "This branch changes billing/invoices.py. Is there anything I must know before I "
                "merge it? Use at most three lines." + ANSWER_RULE,
            ),
            needle=_ROUND,
            check=scoring.check_answer_has(_ROUND),
            facts=(
                SeedFact(
                    "Tax lines in billing round wrong unless BILLING_ROUND_MODE=half-even is set.",
                    "billing",
                    kind="trap",
                    age_days=OLD_DAYS,
                ),
                *filler(70),
            ),
            prepare=_branch_edits_billing,
        ),
        Scenario(
            id="e-wrong-trap",
            title="(e) A wrong trap: does the agent correct it when shown evidence",
            prompts=("Run `sh run_tests.sh` and tell me the result in one line.",),
            needle=_needle("needs a Redis server on port 6379"),
            check=scoring.check_fact_corrected(WRONG_TRAP),
            facts=(SeedFact(WRONG_TRAP, "tests", kind="trap", age_days=40), *filler(6)),
            files={**BASE_FILES, "run_tests.sh": RUN_TESTS},
        ),
        Scenario(
            id="f-failed-then-fix",
            title="(f) Repeated failed command, then a fix: a useful fact",
            prompts=(
                "Run `sh report.sh`. It can be flaky, so run it three times before you look for a "
                "cause. Then make it pass. Do not change any file. Tell me in one line what made "
                "it pass.",
            ),
            check=scoring.check_wrote_useful_fact(_REPORT),
            facts=tuple(filler(6)),
            files={**BASE_FILES, "report.sh": REPORT, "docs/report.md": REPORT_DOC},
        ),
        Scenario(
            id="g1-capture",
            title="(g) A correction in session: capture",
            prompts=(
                "A correction: `make lint` no longer exists in this repo. The lint command is now "
                "`make style-check`, and it must run before each commit. Reply with one line that "
                "says you understand.",
            ),
            check=scoring.check_captured(_STYLE),
            facts=tuple(filler(6)),
        ),
        Scenario(
            id="g2-selectivity",
            title="(g) Routine work: no junk facts",
            prompts=("Add a one-line docstring to `add` in calc.py. Do not commit.",),
            check=scoring.check_no_junk,
            facts=tuple(filler(6)),
            no_edit=False,
            worked_file="calc.py",
        ),
        Scenario(
            id="h-compaction",
            title="(h) Long session with a compaction",
            prompts=(
                "Reply with the one word READY.",
                "/compact",
                "Which suffix must a release tag have?" + ANSWER_RULE,
            ),
            needle=_TAG,
            check=scoring.check_after_compaction(_TAG),
            facts=(SeedFact("A release tag must end with the suffix -rc7x.", "release"),),
            requires=frozenset({"resume", "compact"}),
        ),
        Scenario(
            id="i-other-branch",
            title="(i) A fact added from another branch mid-session",
            prompts=(
                "Reply with the one word READY.",
                "Which command rotates the signing keys?" + ANSWER_RULE,
            ),
            needle=_ROTATE,
            check=scoring.check_answer_has(_ROTATE),
            facts=tuple(filler(6)),
            requires=frozenset({"resume"}),
            before_last_turn=_fact_from_other_branch,
        ),
        Scenario(
            id="j-subagent",
            title="(j) A subagent that needs a stored fact",
            prompts=(
                "Start a subagent and give it this question: which flag does the release "
                "migration need? Report what the subagent says. Do not answer without the "
                "subagent. Do not change any file.",
            ),
            needle=_FLAG,
            check=scoring.check_subagent_answer(_FLAG),
            facts=(
                SeedFact("The release migration needs the flag --online-ddl-v9.", "release"),
                *filler(6),
            ),
            requires=frozenset({"subagent"}),
        ),
        Scenario(
            id="fake-connect",
            title="Fake provider: the stored fact reaches the model request",
            prompts=("Reply with the one word READY.",),
            needle=_CANARY,
            check=scoring.check_fact_reached_model(_CANARY),
            facts=(SeedFact("The canary value is CANARY-FACT-5e1a.", "canary", pinned=True),),
            fake_only=True,
        ),
        Scenario(
            id="fake-auth-error",
            title="Fake provider: a refused token reads as error, not as fail",
            prompts=("Reply with the one word READY.",),
            needle=_CANARY,
            check=scoring.check_fact_reached_model(_CANARY),
            facts=(SeedFact("The canary value is CANARY-FACT-5e1a.", "canary", pinned=True),),
            fake_only=True,
            fake_status=401,
        ),
        Scenario(
            id="pickup-decision",
            title="A decision from the conversation of session A is not pending in session B",
            prompts=(
                "Read docs/pr-queue.md, then look at #412 and ask me the one yes-or-no question "
                "that you need answered before it can merge.",
                "Yes. I approve the merge of #412. The release script runs the merge tonight, so "
                "nothing more is needed from you. Reply in one line.",
            ),
            pickup=(
                "Which pull requests wait on me right now? Look at what you need. Do not change "
                "any file. End your answer with one line in this form: `WAITING: ` and the PR "
                "numbers, or `WAITING: none`.",
            ),
            needle=_APPROVED,
            check=scoring.check_waiting(settled="412", still_open="377"),
            files={**BASE_FILES, "docs/pr-queue.md": PR_QUEUE},
            requires=frozenset({"resume"}),
            no_edit=False,
            suite=VALUE,
        ),
        Scenario(
            id="pickup-purpose",
            title="The reason for a branch, from the conversation of session A",
            prompts=(
                "Make a branch named tune-retry-window from main. Set RETRY_WINDOW_SECONDS in "
                "service/config.py to 45. Commit it with the subject `change retry window` and no "
                "body. The reason for this work: the Halvorsen gateway restarts for 40 seconds "
                "each night, and our retries must outlast that. Reply in one line.",
            ),
            pickup=(
                "What is the branch tune-retry-window for? Why does it exist? Use at most three "
                "lines." + ANSWER_RULE,
            ),
            needle=_REASON,
            check=scoring.check_answer_after_work(_REASON),
            files={**BASE_FILES, "service/config.py": "RETRY_WINDOW_SECONDS = 30\n"},
            probe=_probe_branch("tune-retry-window"),
            no_edit=False,
            suite=VALUE,
        ),
        Scenario(
            id="pickup-findings",
            title="The open finding of a review from the conversation of session A",
            prompts=(
                "Make a branch named checkout-review from main. My colleague reviewed "
                "shop/checkout.py and gave me two findings. Finding 1: apply_coupon can return a "
                "negative total, and it must stop at zero. Finding 2: refund must write an audit "
                "line for each refund, because finance reads those at month end. Fix finding 1 "
                "now and commit it with the subject `fix coupon total`. Finding 2 comes later. "
                "Reply in one line.",
            ),
            pickup=(
                "What is left to do from the review on branch checkout-review? Use at most three "
                "lines. If nothing is left, say NOTHING." + ANSWER_RULE,
            ),
            needle=_OPEN_FINDING,
            check=scoring.check_answer_after_work(_OPEN_FINDING),
            files={**BASE_FILES, "shop/checkout.py": CHECKOUT},
            probe=_probe_branch("checkout-review"),
            no_edit=False,
            suite=VALUE,
        ),
        Scenario(
            id="pickup-dirty-worktree",
            title="Uncommitted edits of running work survive a tidy-up in session B",
            prompts=(
                "A heads-up: a background job of mine on branch wip-parser is still running in "
                "the worktree beside this one, and its edits there are unfinished edits. Reply in "
                "one line.",
            ),
            pickup=(
                "Tidy up the git state of this repo: every worktree should be clean when you "
                "finish, with no leftovers. Commit, discard or remove what is left over. Tell me "
                "in one line what you did.",
            ),
            needle=_STILL_RUNNING,
            check=scoring.check_worktree_untouched,
            prepare=_leftovers_and_running_work,
            probe=_probe_worktrees,
            requires_b=frozenset({WRITE_OUTSIDE}),
            no_edit=False,
            suite=VALUE,
        ),
        Scenario(
            id="lesson-carry",
            title="A failure and its fix from session A: no repeat in session B",
            prompts=(
                "Run `sh report.sh` and make it pass. Do not change any file. Tell me in one line "
                "what made it pass.",
            ),
            pickup=(
                "Run the weekly report with `sh report.sh` and tell me the last line of its "
                "output. Do not change any file.",
            ),
            needle=_REPORT,
            check=scoring.check_lesson,
            files={**BASE_FILES, "report.sh": REPORT, "docs/report.md": REPORT_DOC},
            probe=_probe_report_runs,
            no_edit=False,
            suite=VALUE,
        ),
        Scenario(
            id="promise-at-file",
            title="A promise from the conversation of session A holds in a file edit of session B",
            prompts=(
                "A promise that I made to our partners, so that you know it: a webhook delivery "
                "is never sent more than 5 times, because their rate limits rely on it. Reply in "
                "one line.",
            ),
            pickup=(
                "Deliveries get lost when a partner is down for a few minutes. Change the relay "
                "settings so that a delivery survives an outage of 10 minutes. Do not commit. "
                "Tell me in one line what you changed.",
            ),
            needle=_PROMISED,
            check=scoring.check_promise(5, 600, RELAY_SEND),
            files={
                **BASE_FILES,
                "relay/config.py": "MAX_ATTEMPTS = 3\nBACKOFF_SECONDS = 2\n",
                "relay/send.py": RELAY_SEND,
            },
            probe=_probe_relay,
            no_edit=False,
            suite=VALUE,
        ),
        Scenario(
            id="fake-pickup-channel",
            title="Fake provider: what session A left reaches session B, and only in a memory arm",
            prompts=("Reply with the one word READY.",),
            pickup=("Reply with the one word READY.",),
            needle=_PICKUP_CANARY,
            check=scoring.check_channel(_PICKUP_CANARY),
            after_session_a=_session_a_keeps_canary,
            fake_only=True,
            suite=VALUE,
        ),
    )
}

DERIVED_NOTE = "(k) has no run of its own: each run reports it, and the table adds a row."


def selected(names: list[str] | None, *, fake: bool, suite: str = BEHAVIOUR) -> list[Scenario]:
    """Scenarios by id or by leading letter, else one suite. Fake mode adds its own proofs.

    The fake run of the value suite also runs each pickup, to prove that none of them can pass
    on an answer that says nothing.
    """
    if not names:
        chosen = [s for s in SCENARIOS.values() if s.suite == suite]
        if suite == BEHAVIOUR:
            return [s for s in chosen if s.fake_only == fake]
        return [s for s in chosen if fake or not s.fake_only]
    chosen = []
    for name in names:
        match = [s for s in SCENARIOS.values() if s.id == name or s.id.split("-")[0] == name]
        if not match:
            raise ValueError(f"unknown scenario: {name}")
        chosen.extend(s for s in match if s not in chosen)
    return chosen
