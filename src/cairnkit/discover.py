"""The look-up line of the load footer, and the short rules of a session start."""

from __future__ import annotations

DISCOVER = (
    "Look up: `memory search WORDS`, then `memory show ID`. All of it: `memory instructions`."
)

ADD_LINE = '`memory add "TEXT"`. If nothing is worth a fact, say so and finish.'

CAPTURE_GUIDE = f"""\
Ask: if this session ended now, what would the next agent get wrong? Write a fact for each moment
of this session that the code, git and docs do not hold:
- The owner decided or approved something.
- A promise or a limit.
- A review found something.
- Work started or was handed off: its purpose and its next step.
- A failure and its fix.
- Something written earlier is no longer true: replace it with `--supersedes ID`.
A good fact gives the reason and not only the change, in one or two sentences. It names the files
it applies to when it has any. A routine step is not a fact.
{ADD_LINE}"""

RULES_SHORT = """\
Memory rules: save a decision, trap, lesson or correction with `memory add "TEXT"`
(`--short` for a branch note). Replace a fact with `--supersedes ID`. End one with
`memory change ID --status expired|wrong`. Never store a secret or edit memory files."""
