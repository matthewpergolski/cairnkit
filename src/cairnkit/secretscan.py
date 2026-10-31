"""Find text that looks like a secret. A fact must never hold one.

A match counts unless the shape of its value clearly says otherwise. Only `memory purge` can
remove a stored secret, so a value that fits no harmless shape stays a secret.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import NamedTuple

WORD = re.compile(r"[a-z]{1,15}\d{0,2}")
NUMBER = re.compile(r"\d{1,4}")
PATH_PART = re.compile(r"(?:[a-z]{1,20}|[A-Z][a-z]{0,19}|[A-Z]{1,20})\d{0,2}")
# `settings.API_KEY`, `os.environ[`, `getpass()`. The scan stops at a quote, so `[` can end it.
REFERENCE = re.compile(r"[A-Za-z_]+\d{0,2}(?:\.[A-Za-z_]+\d{0,2})*(?:\.[A-Za-z_]+\d{0,2}|\[|\(\)?)")
PLACEHOLDER = re.compile(
    r"(?i)(?:pass|password|passwd|pwd|secret|changeme|change[_-]me|example|placeholder|dummy"
    r"|x{3,}|\*{3,}|your[_-]\S*)"
)
# An environment variable or a template field in place of the value.
TEMPLATE = re.compile(r"\$\w+|\$\{[^}]*\}|<[^>]*>|\{[^}]*\}|%s")
# These names mean "secret" by themselves. `SORT_KEY` or `?code=` can name something ordinary.
SECRET_NAME = re.compile(r"(?i)secret|token|password|passwd|pwd|api[_-]?key|auth")


def _is_word(part: str) -> bool:
    if not WORD.fullmatch(part):
        return False
    return len(part) <= 3 or any(vowel in part for vowel in "aeiouy")


def is_words(value: str) -> bool:
    """Kebab-case English: `tokens-must-be-rotated-every-30-days`."""
    parts = value.rstrip(".,;:)").split("-")
    words = sum(_is_word(part) for part in parts)
    numbers = sum(bool(NUMBER.fullmatch(part)) for part in parts)
    return len(parts) >= 3 and words + numbers == len(parts) and words > numbers


def _is_path(value: str) -> bool:
    match = re.fullmatch(r"(?:~|\.{1,2})?((?:/[^/]+)+)/?", value)
    if not match:
        return False
    parts = match[1].strip("/").split("/")
    return len(parts) >= 2 and all(
        PATH_PART.fullmatch(piece) for part in parts for piece in part.split(".")
    )


def _is_not_a_value(value: str) -> bool:
    """The text names where a value is, or stands in for one."""
    return bool(REFERENCE.fullmatch(value)) or _is_path(value) or bool(PLACEHOLDER.fullmatch(value))


def _assigned_name(match: re.Match[str]) -> bool:
    value = match["value"]
    if _is_not_a_value(value):
        return True
    if SECRET_NAME.search(match["name"]):
        return False
    return _is_word(value) or all(_is_word(part) for part in re.split(r"[_-]", value))


def _url_parameter(match: re.Match[str]) -> bool:
    return not SECRET_NAME.search(match["name"]) and _is_word(match["value"])


def _url_password(match: re.Match[str]) -> bool:
    value = match["value"]
    return bool(PLACEHOLDER.fullmatch(value) or TEMPLATE.fullmatch(value))


class Shape(NamedTuple):
    name: str
    pattern: re.Pattern[str]
    harmless: Callable[[re.Match[str]], bool] = lambda match: False


SHAPES: list[Shape] = [
    Shape("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    Shape("AWS access key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    Shape(
        "GitHub token",
        re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"),
    ),
    Shape("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    Shape("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    Shape(
        "API secret key",
        re.compile(r"\b(sk|rk)-[A-Za-z0-9_-]{20,}"),
        lambda match: is_words(match[0]),
    ),
    Shape("payment key", re.compile(r"\b(sk|rk)_(live|test)_[A-Za-z0-9]{16,}")),
    Shape(
        "bearer token",
        re.compile(r"\bBearer\s+(?P<value>[A-Za-z0-9._~+/-]{16,})"),
        lambda match: is_words(match["value"]),
    ),
    Shape(
        "secret in URL",
        re.compile(
            r"(?i)[?&](?P<name>k|key|token|secret|code|sig|signature|api[_-]?key|access[_-]?token"
            r"|auth)=(?P<value>[^\s&#]{6,})"
        ),
        _url_parameter,
    ),
    Shape(
        "assigned secret name",
        re.compile(
            r"\b(?!(?:EXIT|STATUS|ERROR|RETURN|REASON|RESPONSE|HTTP|ZIP|POSTAL|COUNTRY|LANG|"
            r"LANGUAGE|PUBLIC)_)(?![A-Z0-9_]*PUBLIC_KEY\b)"
            r"(?P<name>[A-Z][A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_?KEY|_KEY|_CODE))"
            r"\s*[:=]\s*['\"]?(?P<value>[^\s'\"$<{]{6,})"
        ),
        _assigned_name,
    ),
    Shape(
        "JSON web token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    ),
    Shape(
        "password in URL",
        re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:@]+:(?P<value>[^\s/@]+)@"),
        _url_password,
    ),
    Shape(
        "assigned secret",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)"
            r"\s*[:=]\s*['\"]?(?P<value>[^\s'\"$<{][^\s'\"]{5,})"
        ),
        lambda match: _is_not_a_value(match["value"]),
    ),
]


def find_secrets(text: str) -> list[str]:
    """Return the names of the secret shapes found in text."""
    return [
        shape.name
        for shape in SHAPES
        if any(not shape.harmless(match) for match in shape.pattern.finditer(text))
    ]
