"""The look-up line of the load, the short rules of a session start, and the capture guide."""

from __future__ import annotations

DISCOVER = (
    "Look up: `memory search WORDS`, then `memory show ID`. All of it: `memory instructions`."
)

ADD_LINE = (
    '`memory add "TEXT" --basis told` for what the owner said, else `--basis seen`. If nothing is '
    "worth a fact, say so and finish."
)

# Each block prints this. The 157 words before this guide were 43 percent of all hook words.
# `--supersedes ID` is in RULES_SHORT, which each session reads at its start.
CAPTURE_GUIDE = (
    "Ask: what would the next agent get wrong if this session ended now? Write a fact for each "
    "moment it had: an owner decision or approval, a promise or a limit, a review finding, the "
    "purpose and next step of started work, or a failure and its fix. Give the reason and the "
    f"files. A commit, a branch or the diff is no fact.\n{ADD_LINE}"
)

RULES_SHORT = """\
Memory rules: save a decision, trap, lesson or correction with `memory add "TEXT"`
(`--short` for a branch note). Replace a fact with `--supersedes ID`. End one with
`memory change ID --status expired|wrong`. Never store a secret or edit memory files."""
