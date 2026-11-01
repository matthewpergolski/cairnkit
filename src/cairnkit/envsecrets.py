"""Real secret values from the untracked `.env*` files of a checkout.

The values stay in memory for one run. They are never written and never printed: a match
returns only the variable name and the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

from cairnkit.paths import Project, run_git
from cairnkit.secretscan import (
    ENV_VALUE,
    FIELD_PARTS,
    Label,
    is_not_a_value,
    label_of,
    looks_made_up,
    mask_token,
    name_parts,
)

ENV_NAME = re.compile(r"\.env(?:rc)?(?:[._-].+)?")
NOT_REAL = re.compile(r"(?i)example|sample|template|dist\b|defaults?\b")
LINE = re.compile(r"\s*(?:export\s+)?([A-Za-z_]\w*)\s*=\s*(.*)")
SKIP_FOLDERS = frozenset(
    {"node_modules", "vendor", "venv", "dist", "build", "target", "out", "coverage", "__pycache__"}
)
SEARCH_DEPTH = 2
MAX_FOLDERS = 300
MAX_FILE_BYTES = 256 * 1024
GIT_TIMEOUT = 1.0
# Below this length, a value is an ordinary word too often: `admin`, `root`.
MIN_LENGTH = 6
# At this length, a value with no space is no word that a fact would name by chance.
LONG_VALUE = 20
# These names say what the value is: `AWS_REGION=us-east-1` is no secret and a fact can name it.
PLAIN_FIELDS = FIELD_PARTS | {"version", "email"}
URL_PASSWORD = re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:@]*:([^\s/@]+)@")
# Local defaults. A fact can name these without any secret in it.
ORDINARY_VALUES = frozenset(
    {
        "postgres",
        "postgresql",
        "mysql",
        "mariadb",
        "mongodb",
        "redis",
        "localhost",
        "development",
        "production",
        "staging",
        "docker",
    }
)


class Found(NamedTuple):
    name: str
    file: str
    # Only its name says secret. The value is a plain word, so a fact can hold it by chance.
    plain: bool

    @property
    def label(self) -> str:
        return f"value of {self.name} in {self.file}"


class EnvValues:
    """The values, each with the variable and the file that hold it."""

    def __init__(self, found: dict[str, Found] | None = None) -> None:
        self._found = found or {}
        longest_first = sorted(self._found, key=len, reverse=True)
        words = "|".join(map(re.escape, longest_first))
        self._pattern = (
            re.compile(rf"(?<![A-Za-z0-9_])(?:{words})(?![A-Za-z0-9_])") if words else None
        )
        self._plain = {item.label for item in self._found.values() if item.plain}

    def __repr__(self) -> str:
        return f"EnvValues({len(self._found)} value(s))"

    def find(self, text: str) -> list[str]:
        if self._pattern is None:
            return []
        return sorted({self._found[match[0]].label for match in self._pattern.finditer(text)})

    def mask(self, text: str) -> str:
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda match: self._token(self._found[match[0]].name), text)

    @staticmethod
    def _token(name: str) -> str:
        return mask_token(name if re.fullmatch(r"[A-Z][A-Z0-9_]{0,39}", name) else ENV_VALUE)

    def only_plain(self, names: list[str]) -> bool:
        """Each name comes from a plain word in a `.env` file, and no shape matched."""
        return bool(names) and all(name in self._plain for name in names)


def _env_files(root: Path) -> list[Path]:
    """The `.env*` files near the root. This runs at each session start, so it stays shallow."""
    found: list[Path] = []
    folders = [(root, 0)]
    seen = 0
    while folders and seen < MAX_FOLDERS:
        folder, depth = folders.pop(0)
        seen += 1
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if ENV_NAME.fullmatch(entry.name):
                        if not NOT_REAL.search(entry.name) and entry.is_file():
                            found.append(Path(entry.path))
                    elif (
                        depth < SEARCH_DEPTH
                        and not entry.name.startswith(".")
                        and entry.name not in SKIP_FOLDERS
                        and entry.is_dir(follow_symlinks=False)
                    ):
                        folders.append((Path(entry.path), depth + 1))
        except OSError:
            continue
    return found


def _untracked(root: Path, files: list[Path], is_git: bool) -> list[Path]:
    if not files or not is_git:
        return files
    names = [str(path.relative_to(root)) for path in files]
    tracked = run_git(root, "ls-files", "--", *names, timeout=GIT_TIMEOUT) or ""
    known = set(tracked.splitlines())
    return [path for path, name in zip(files, names, strict=True) if name not in known]


def _parse_value(raw: str) -> str:
    raw = raw.strip()
    if raw[:1] in ("'", '"'):
        end = raw.find(raw[0], 1)
        return raw[1:end] if end > 0 else ""
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def _not_a_word(value: str) -> bool:
    return looks_made_up(value) or (len(value) >= LONG_VALUE and not re.search(r"\s", value))


def _classify(name: str, value: str) -> bool | None:
    """None: no secret. Else whether the value is a plain word, the `Found.plain` flag."""
    if len(value) < MIN_LENGTH or is_not_a_value(value):
        return None
    # POSTGRES_PASSWORD=postgres: a local default that each mention of the tool would match.
    if value.lower() in ORDINARY_VALUES or value.lower() in name_parts(name):
        return None
    label = label_of(name)
    if label is Label.STRONG:
        return not _not_a_word(value)
    if not _not_a_word(value) or re.search(r"\s", value):
        return None
    if label is Label.NONE and (value.isdigit() or PLAIN_FIELDS & {*name_parts(name)[-1:]}):
        return None
    # BRAND_TEXT=GitHub: mixed case with no secret name can be a plain word in a true fact.
    return label is Label.NONE and len(value) < LONG_VALUE and not re.search(r"\d", value)


def _values_in(path: Path) -> list[tuple[str, str, bool]]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found = []
    for line in text.splitlines():
        match = LINE.fullmatch(line)
        if not match or line.lstrip().startswith("#"):
            continue
        name, value = match[1], _parse_value(match[2])
        plain = _classify(name, value)
        if plain is not None:
            found.append((name, value, plain))
        url = URL_PASSWORD.match(value)
        if url:
            for password in {url[1], unquote(url[1])}:
                plain = _classify("PASSWORD", password)
                if plain is not None:
                    found.append((name, password, plain))
    return found


def read_env_values(project: Project) -> EnvValues:
    """Read the checkout and, from a worktree, the main checkout. This never raises."""
    found: dict[str, Found] = {}
    for root in dict.fromkeys((project.root, project.main_root)):
        for path in _untracked(root, _env_files(root), project.is_git):
            for name, value, plain in _values_in(path):
                found.setdefault(value, Found(name, str(path.relative_to(root)), plain))
    return EnvValues(found)
