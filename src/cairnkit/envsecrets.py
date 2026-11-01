"""Real secret values from the untracked `.env*` files of a checkout.

The values stay in memory for one run. They are never written and never printed: a match
returns only the variable name and the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from cairnkit.paths import Project, run_git
from cairnkit.secretscan import Label, is_not_a_value, label_of, name_parts

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


class EnvValues:
    """The values, each with the variable and the file that hold it."""

    def __init__(self, labels: dict[str, str] | None = None) -> None:
        self._labels = labels or {}
        longest_first = sorted(self._labels, key=len, reverse=True)
        words = "|".join(map(re.escape, longest_first))
        self._pattern = (
            re.compile(rf"(?<![A-Za-z0-9_])(?:{words})(?![A-Za-z0-9_])") if words else None
        )

    def __repr__(self) -> str:
        return f"EnvValues({len(self._labels)} value(s))"

    def find(self, text: str) -> list[str]:
        if self._pattern is None:
            return []
        return sorted({self._labels[match[0]] for match in self._pattern.finditer(text)})


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


def _is_real(name: str, value: str) -> bool:
    if label_of(name) is not Label.STRONG or len(value) < MIN_LENGTH:
        return False
    # POSTGRES_PASSWORD=postgres: a local default that each mention of the tool would match.
    if value.lower() in ORDINARY_VALUES or value.lower() in name_parts(name):
        return False
    return not is_not_a_value(value)


def _values_in(path: Path) -> list[tuple[str, str]]:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return []
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    pairs = []
    for line in text.splitlines():
        match = LINE.fullmatch(line)
        if match and not line.lstrip().startswith("#"):
            value = _parse_value(match[2])
            if _is_real(match[1], value):
                pairs.append((match[1], value))
    return pairs


def read_env_values(project: Project) -> EnvValues:
    """Read the checkout and, from a worktree, the main checkout. This never raises."""
    labels: dict[str, str] = {}
    for root in dict.fromkeys((project.root, project.main_root)):
        for path in _untracked(root, _env_files(root), project.is_git):
            for name, value in _values_in(path):
                labels.setdefault(value, f"value of {name} in {path.relative_to(root)}")
    return EnvValues(labels)
