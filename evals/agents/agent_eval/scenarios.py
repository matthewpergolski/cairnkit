"""The scripted scenarios. Prompts never name the memory: the test is a hands-off session."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from agent_eval import scoring

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


@dataclass(frozen=True)
class Scenario:
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

    @property
    def calls(self) -> int:
        return len(self.prompts)

    @property
    def runs_without_memory(self) -> bool:
        return False


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
    )
}

DERIVED_NOTE = "(k) has no run of its own: each run reports it, and the table adds a row."


def selected(names: list[str] | None, *, fake: bool) -> list[Scenario]:
    """Scenarios by id or by leading letter. Fake mode defaults to its two proofs."""
    if not names:
        return [s for s in SCENARIOS.values() if s.fake_only == fake]
    chosen = []
    for name in names:
        match = [s for s in SCENARIOS.values() if s.id == name or s.id.split("-")[0] == name]
        if not match:
            raise ValueError(f"unknown scenario: {name}")
        chosen.extend(s for s in match if s not in chosen)
    return chosen
