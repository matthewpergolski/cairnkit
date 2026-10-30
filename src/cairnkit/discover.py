"""One discoverability blurb for session-start, load footers, and --help."""

from __future__ import annotations

DISCOVER = (
    "Look up: `memory search WORDS`. Read one: `memory show ID`. "
    "Pin for every session: `--pinned`. Link: `memory change ID --link related:OTHER`. "
    "Clean up: `memory tidy`."
)

RULES_SHORT = f"""\
Memory rules: record what a later session needs with `memory add` (decisions,
traps, lessons: long-term; working notes: `--short --until-merged`). Optional
`--summary` for a long body. To change a fact, add a newer one (`--supersedes ID`)
or mark it `expired` or `wrong` with `memory change`. Never store secrets. Never
edit memory files by hand. Run `memory instructions` for the full rules.
{DISCOVER}"""
