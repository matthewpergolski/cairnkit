"""Find text that looks like a secret. A fact must never hold one."""

from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("API secret key", re.compile(r"\b(sk|rk)-[A-Za-z0-9_-]{20,}")),
    (
        "JSON web token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ),
    ("password in URL", re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@")),
    (
        "assigned secret",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
            r"\s*[:=]\s*['\"]?[^\s'\"]{6,}"
        ),
    ),
]


def find_secrets(text: str) -> list[str]:
    """Return the names of the secret patterns found in text."""
    return [name for name, pattern in PATTERNS if pattern.search(text)]
