"""The look-up line of the load footer, and the short rules of a session start."""

from __future__ import annotations

DISCOVER = (
    "Look up: `memory search WORDS`, then `memory show ID`. All of it: `memory instructions`."
)

RULES_SHORT = """\
Memory rules: save a decision, trap, lesson or correction with `memory add "TEXT"`
(`--short` for a branch note). Replace a fact with `--supersedes ID`. End one with
`memory change ID --status expired|wrong`. Never store a secret or edit memory files."""
