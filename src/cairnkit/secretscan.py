"""Find text that looks like a secret. A fact must never hold one.

The two errors do not cost the same. A false refusal costs the agent one rewording. A stored
secret prints in each session load, reaches the model provider, and needs `memory purge`. So a
value behind a secret label is refused unless its shape clearly says that it is no value: a
real path, a code reference, a placeholder or a template.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from enum import Enum
from functools import lru_cache
from typing import NamedTuple, Protocol


class Label(Enum):
    NONE = "none"
    # `INVITE_CODE`: a word can be an ordinary value, so only a value that is no word counts.
    WEAK = "weak"
    STRONG = "strong"


# A name part that ends in one of these means a secret. The plural forms stay out, because
# `max_tokens=4096` and `secrets: inherit` hold no secret.
SECRET_ENDINGS = (
    "password",
    "passwd",
    "passphrase",
    "passcode",
    "pwd",
    "secret",
    "token",
    "credential",
    "apikey",
    "secretkey",
    "accesskey",
    "privatekey",
    "signingkey",
    "encryptionkey",
    "sshkey",
)
# The last part says what the name holds: `PASSWORD_FILE` holds a path, `token_ttl` a number.
FIELD_PARTS = frozenset(
    [
        "age",
        "algo",
        "algorithm",
        "audience",
        "count",
        "dir",
        "disabled",
        "domain",
        "enabled",
        "endpoint",
        "env",
        "expires",
        "expiry",
        "expiration",
        "field",
        "file",
        "header",
        "host",
        "hosts",
        "id",
        "issuer",
        "label",
        "len",
        "length",
        "lifetime",
        "limit",
        "max",
        "min",
        "mode",
        "name",
        "path",
        "policy",
        "port",
        "prefix",
        "provider",
        "ref",
        "region",
        "required",
        "scope",
        "size",
        "timeout",
        "ttl",
        "type",
        "uri",
        "url",
        "user",
        "username",
        "var",
    ]
)
# Keys of data, not of a lock.
DATA_KEYS = frozenset(
    [
        "cache",
        "composite",
        "dict",
        "foreign",
        "group",
        "hash",
        "idempotency",
        "index",
        "item",
        "join",
        "lookup",
        "map",
        "object",
        "order",
        "package",
        "partition",
        "primary",
        "public",
        "range",
        "routing",
        "shard",
        "sort",
        "unique",
    ]
)
ORDINARY_CODES = frozenset(
    [
        "exit",
        "status",
        "error",
        "return",
        "reason",
        "response",
        "http",
        "zip",
        "postal",
        "country",
        "lang",
        "language",
        "public",
    ]
)

WORD = re.compile(r"[a-z]{1,15}\d{0,2}")
NUMBER = re.compile(r"\d{1,4}")
PATH_PIECE = re.compile(r"(?:[a-z]{1,20}|[A-Z][a-z]{0,19}|[A-Z]{1,20})\d{0,5}|\d{1,5}")
KEY_FILE = re.compile(r"[\w.-]+\.(?:pem|key|crt|cer|p12|pfx|gpg|age|enc|txt|json|ya?ml|toml|env)")
IDENTIFIER = r"[A-Za-z_]+\d{0,2}"
# After a name of letters, `(` or `[` is code. `hunter2(abc` has a digit, so it is no call.
CALL = re.compile(rf"[A-Za-z_][A-Za-z_.]*[(\[].*|{IDENTIFIER}(?:\.{IDENTIFIER})*(?:\(\)?|\[)")
CODE_ROOTS = frozenset(
    [
        "settings",
        "config",
        "conf",
        "cfg",
        "env",
        "ENV",
        "process",
        "os",
        "sys",
        "self",
        "this",
        "app",
        "args",
        "opts",
        "options",
        "params",
        "ctx",
        "context",
        "request",
        "req",
        "secrets",
        "vault",
        "vars",
        "var",
        "import",
        "Rails",
    ]
)
PLACEHOLDER = re.compile(
    r"(?i)(?:pass|password|passwd|pwd|passphrase|secret|token|key|changeme|change[_-]me|example"
    r"|placeholder|dummy|sample|default|test|testing|foo|bar|baz|foobar|value|val"
    r"|none|null|nil|true|false|undefined|empty|blank|unset|yes|no|n/a"
    r"|required|optional|missing|invalid|expired|revoked|rotated|hidden|redacted|masked|hashed"
    r"|await|new|from|via|see|stored|unused"
    r"|(?:str|string|bytes|int|bool|any|object)(?:\|\w+)?"
    r"|x{3,}|\*+|\.{2,}|_+|-+|your[_-]\S*|my[_-]\S*|some[_-]\S*|\S*[_-]here)"
)
# An environment variable or a template field in place of the value.
TEMPLATE = re.compile(r"\$\w+|\$\{[^}]*\}|<[^>]*>|\{[^}]*\}|%\w*%?")
URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+")
# These names mean "secret" by themselves. `SORT_KEY` or `?code=` can name something ordinary.
SECRET_NAME = re.compile(r"(?i)secret|token|password|passwd|pwd|api[_-]?key|auth")

# What English says after "the password is" that holds a digit.
ALGORITHM = re.compile(
    r"(?i)(?:sha|md|hs|rs|es|ps|aes|rsa|base|utf|oauth|pbkdf|argon|bcrypt|scrypt|blake|crc)"
    r"\d*(?:id)?(?:[-_]\w+)?"
)
AMOUNT = re.compile(
    r"(?i)~?\d+[-_]?(?:bits?|bytes?|chars?|characters?|digits?|letters?|words?|long"
    r"|[hmsd]|secs?|seconds?|mins?|minutes?|hours?|days?|weeks?|months?|years?)"
)
VERSION = re.compile(r"v?\d+(?:\.\d+)+")
MADE_UP = re.compile(r"[a-z][A-Z]|\w[@#%^&*!]\w?")

MIN_VALUE = 4
MIN_PROSE_DIGITS = 6
MIN_WEAK_VALUE = 6

# A lookahead, so that `login: password=abc` still finds the second label.
VALUE = r"""(?="(?P<dq>[^"\n]*)"|'(?P<sq>[^'\n]*)'|`(?P<bq>[^`\s]*)`|(?P<bare>[^\s'"`]+))"""


def name_parts(name: str) -> list[str]:
    """`dbPassword2`, `DB_PASSWORD2` and `db-password` all give ["db", "password"]."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    parts = re.split(r"[^A-Za-z0-9]+", spaced)
    return [part.lower().rstrip("0123456789") for part in parts if part]


def label_of(name: str) -> Label:
    """How much this name says that its value is a secret."""
    parts = name_parts(name)
    if not parts or (len(parts) > 1 and parts[-1] in FIELD_PARTS) or parts[0] == "no":
        return Label.NONE
    if any(part.endswith(SECRET_ENDINGS) for part in parts):
        return Label.STRONG
    if len(parts) == 1:
        return Label.NONE
    if parts[-1] in ("pass", "auth", "cookie"):
        return Label.STRONG
    if parts[-1] == "key":
        return Label.NONE if parts[-2] in DATA_KEYS else Label.STRONG
    if parts[-1] == "code" and name.isupper() and parts[0] not in ORDINARY_CODES:
        return Label.WEAK
    return Label.NONE


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
    body = re.sub(r"^(?:~|\.{1,2})?/", "", value, count=1)
    if body == value and "/" not in value:
        return bool(KEY_FILE.fullmatch(value))
    parts = body.rstrip("/").split("/")
    if len(parts) == 1 and body != value:
        return parts[0].isalpha() and parts[0].islower()
    return all(
        PATH_PIECE.fullmatch(piece)
        for part in parts
        for piece in re.split(r"[._-]", part.lstrip("."))
    )


def _is_reference(value: str) -> bool:
    """Code that names where a value is: `settings.API_KEY`, `os.environ[`, `getpass()`."""
    if CALL.fullmatch(value):
        return True
    parts = value.split(".")
    if not all(re.fullmatch(IDENTIFIER, part) for part in parts):
        return False
    if len(parts) == 1:
        return "_" in value and label_of(value) is Label.STRONG
    last = parts[-1]
    return parts[0] in CODE_ROOTS or last.isupper() or label_of(last) is Label.STRONG


def is_not_a_value(value: str) -> bool:
    """The text names where a value is, or stands in for one."""
    return (
        value[:1] in ("$", "<", "{", "(")
        or any(mark in value for mark in ("${", "{{", "]("))
        or bool(TEMPLATE.fullmatch(value) or PLACEHOLDER.fullmatch(value) or URL.fullmatch(value))
        or _is_reference(value)
        or _is_path(value)
    )


def _value(match: re.Match[str]) -> tuple[str, bool]:
    """The value of a match, and whether it was in quotes."""
    bare = match["bare"]
    if bare is None:
        return next(match[g] for g in ("dq", "sq", "bq") if match[g] is not None), True
    bare = bare.strip("*").rstrip(".,;:!")
    for closing, opening in ((")", "("), ("}", "{"), ("]", "[")):
        if bare.endswith(closing) and opening not in bare:
            bare = bare.rstrip(closing + ".,;:!")
    return bare, False


def _looks_made_up(value: str) -> bool:
    """English does not hold this word: it has a digit, a capital inside it, or a symbol."""
    if ALGORITHM.fullmatch(value) or AMOUNT.fullmatch(value) or VERSION.fullmatch(value):
        return False
    if value.isdigit():
        return len(value) >= MIN_PROSE_DIGITS
    has_digit = any(char.isdigit() for char in value) and any(char.isalpha() for char in value)
    return has_digit or bool(MADE_UP.search(value))


def _assigned_name(match: re.Match[str]) -> bool:
    label = label_of(match["name"])
    if label is Label.NONE:
        return True
    value, _ = _value(match)
    if value.lower() == match["name"].lower() or is_not_a_value(value):
        return True
    if label is Label.WEAK:
        words = re.split(r"[_-]", value)
        return len(value) < MIN_WEAK_VALUE or _is_word(value) or all(map(_is_word, words))
    return len(value) < MIN_VALUE


def _spoken(match: re.Match[str]) -> bool:
    """In prose, only a quote or a word that no English holds says that this is a value."""
    if "name" in match.groupdict() and label_of(match["name"]) is not Label.STRONG:
        return True
    value, quoted = _value(match)
    if len(value) < MIN_VALUE or is_not_a_value(value):
        return True
    return not (quoted or _looks_made_up(value))


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
    Shape(
        "service token",
        re.compile(
            r"\b(?:whsec_[A-Za-z0-9+/=_-]{10,}|npm_[A-Za-z0-9]{20,}|gl(?:pat|rt)-[A-Za-z0-9_-]{10,}"
            r"|sb_secret_[A-Za-z0-9_-]{10,}|pypi-[A-Za-z0-9_-]{30,}|hf_[A-Za-z0-9]{30,}"
            r"|dop_v1_[a-f0-9]{30,}|shp(?:at|ss)_[a-f0-9]{20,})"
        ),
    ),
    Shape(
        "basic auth header",
        re.compile(
            r"(?i)\bauthorization['\"]?\s*[:=]\s*['\"]?basic\s+(?P<value>[A-Za-z0-9+/]{8,}={0,2})"
        ),
        lambda match: match["value"].isalpha() and match["value"].islower(),
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
            r"(?<![\w.])(?P<name>[A-Za-z][\w.-]*)['\"`]?\s*(?::=|=>|==|=|:)\s*\**\s*" + VALUE
        ),
        _assigned_name,
    ),
    Shape(
        "secret after a flag",
        re.compile(r"(?<!\S)--(?P<name>[A-Za-z][\w-]*)\s+" + VALUE),
        _spoken,
    ),
    Shape(
        "secret in prose",
        re.compile(
            r"(?i)(?<![A-Za-z])(?:pass(?:word|phrase|code|wd)|pwd|secret|token"
            r"|(?:api|access|secret|private|ssh|deploy)[ _-]?key)(?![A-Za-z_-])['\"`]?"
            r"(?:\s+(?:for|on|of|in|at|to)\s+[\w.-]+)?"
            r"\s+(?:(?:is|was)(?:\s+(?:now|still|currently|set\s+to))?"
            r"|(?:set|changed|reset|rotated|updated)\s+to)\s+" + VALUE
        ),
        _spoken,
    ),
]


class KnownValues(Protocol):
    """Real values from the checkout. `find` names them, and it never returns a value."""

    def find(self, text: str) -> list[str]: ...


# Fields that a tool writes from a closed set. Scanning them costs time and finds nothing.
UNSCANNED_FIELDS = frozenset(
    [
        "type",
        "id",
        "kind",
        "basis",
        "status",
        "scope",
        "writer",
        "at",
        "learned_at",
        "happened_at",
        "expires_at",
        "purged_at",
        "cid",
        "rel",
    ]
)


# Each shape needs one of these. Each memory open scans each fact, and most facts hold none.
# tests/test_secret_shapes.py proves that this finds all that the shapes find.
CLUE = re.compile(
    r"-----BEGIN|\b(?:AKIA|ASIA|xox|AIza|eyJ)|\bgh[pousr]_|github_pat_|\b[sr]k[-_]|\bBearer\b|[?&]\w+="
    r"|://|\b(?:whsec_|npm_|gl(?:pat|rt)-|pypi-|hf_|dop_v1_|shp(?:at|ss)_)"
    r"|(?i:pass|pwd|secret|token|credential|key|auth|cookie)|[A-Z]_CODE\b"
)


def match_shapes(text: str) -> tuple[str, ...]:
    return tuple(
        shape.name
        for shape in SHAPES
        if any(not shape.harmless(match) for match in shape.pattern.finditer(text))
    )


# A session start opens the memory more than once, and each fact has the same text each time.
@lru_cache(maxsize=50_000)
def _shapes_in(text: str) -> tuple[str, ...]:
    return match_shapes(text) if CLUE.search(text) else ()


def find_secrets(text: str, known: KnownValues | None = None) -> list[str]:
    """Return the names of the secret shapes and known values found in text."""
    found = list(_shapes_in(text))
    return found + known.find(text) if known else found


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in UNSCANNED_FIELDS:
                yield from _strings(item)


def find_in_record(record: dict, known: KnownValues | None = None) -> list[str]:
    """Return the names found in any field of a record that holds free text."""
    return sorted({name for text in _strings(record) for name in find_secrets(text, known)})
