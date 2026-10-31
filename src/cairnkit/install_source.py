"""Where `memory` was installed from, and whether that source has something newer.

The source is a local folder or a git URL. It comes from `--source`, from the
uv receipt, or from the install record that `memory update` writes. The check
for the session start is cached for a day and never raises.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import unquote, urlparse

from cairnkit import __version__
from cairnkit.clock import now, parse_time, stamp
from cairnkit.skills import cache_dir, is_behind

PACKAGE = "cairnkit"
RECORD = "cairnkit-install.json"
# The names before the rename. An install made under them updates to the new names.
OLD_PACKAGE = "project-memory"
OLD_RECORD = "project-memory-install.json"
RECEIPT = "uv-receipt.toml"
CACHE = "update-check.json"
FRESH = timedelta(days=1)
FRESH_AFTER_FAILURE = timedelta(hours=1)
# Build, cache and log files that are not source. This is not a full ignore-rules reader.
SKIP_DIRS = {"__pycache__", "build", "dist", "node_modules", "htmlcov", "venv", "env"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".log", ".tmp", ".swp", ".bak", "~")


class SourceError(Exception):
    """A step failed. The message says what; `fix` says what to do."""

    def __init__(self, message: str, fix: str):
        super().__init__(message)
        self.fix = fix


@dataclass(frozen=True)
class Source:
    spec: str  # an absolute folder path, or a git URL without the git+ prefix
    kind: str  # "folder" or "git"
    editable: bool = False

    @property
    def label(self) -> str:
        return f"{self.spec} ({self.kind})"

    @property
    def install_spec(self) -> str:
        return self.spec if self.kind == "folder" else f"git+{self.spec}"


@dataclass(frozen=True)
class Latest:
    commit: str | None
    version: str | None


# --- the machine: stubbed in tests ----------------------------------------------------


def tool_env() -> Path:
    """The uv tool environment that runs this code."""
    return Path(sys.prefix)


def target_env() -> Path:
    """The uv tool environment that an update installs into.

    uv names the environment after the package. An install under the old name
    gets a new environment beside it.
    """
    env = tool_env()
    return env.parent / PACKAGE if env.name == OLD_PACKAGE else env


def current_version() -> str:
    return __version__


def git_env() -> dict[str, str]:
    """The environment for git: it never asks for a password and waits, and its
    messages are in English, so update.refuses_commit_id can read them."""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


def git(args: list[str], timeout: float = 3.0) -> str | None:
    """Stdout of a git command, or None when it fails."""
    try:
        done = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            stdin=subprocess.DEVNULL,
            env=git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def spawn_check() -> None:
    """Run `memory update --check` in the background. It writes the cache."""
    with contextlib.suppress(OSError):
        subprocess.Popen(
            [sys.executable, "-m", "cairnkit", "update", "--check"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


# --- the source -----------------------------------------------------------------------


def parse(spec: str, editable: bool = False) -> Source:
    text = spec.strip()
    if text.startswith("git+"):
        return Source(text[4:], "git")
    if "://" in text or text.startswith("git@"):
        return Source(text, "git")
    return Source(str(Path(text).expanduser().resolve()), "folder", editable)


def _receipt() -> dict:
    try:
        return tomllib.loads((tool_env() / RECEIPT).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def from_receipt() -> Source | None:
    for req in _receipt().get("tool", {}).get("requirements", []):
        if not isinstance(req, dict) or req.get("name") not in (PACKAGE, OLD_PACKAGE):
            continue
        if isinstance(req.get("editable"), str):
            return parse(req["editable"], editable=True)
        if isinstance(req.get("directory"), str):
            return parse(req["directory"])
        if isinstance(req.get("git"), str):
            return parse("git+" + req["git"])
    return None


def entrypoint() -> str | None:
    """The installed `memory` command."""
    for entry in _receipt().get("tool", {}).get("entrypoints", []):
        if isinstance(entry, dict) and entry.get("name") == "memory":
            path = entry.get("install-path")
            if isinstance(path, str) and Path(path).is_file():
                return path
    return shutil.which("memory")


def read_record() -> dict:
    for name in (RECORD, OLD_RECORD):
        try:
            data = json.loads((tool_env() / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return data if isinstance(data, dict) else {}
    return {}


def write_record(source: Source, commit: str | None, version: str) -> None:
    record = {
        "source": source.install_spec,
        "commit": commit,
        "version": version,
        "installed_at": stamp(now()),
    }
    target_env().mkdir(parents=True, exist_ok=True)
    (target_env() / RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def installed(flag: str | None) -> tuple[Source | None, str | None]:
    """The source, and the commit installed from it when the record knows it."""
    record = read_record()
    recorded = parse(record["source"]) if isinstance(record.get("source"), str) else None
    source = parse(flag) if flag else (from_receipt() or recorded)
    commit = record.get("commit")
    # A record for another source or another version is from an older install.
    if source != recorded or record.get("version") != current_version():
        commit = None
    return source, commit if isinstance(commit, str) else None


_VERSION_ASSIGN = re.compile(r"""^(?:__version__|VERSION)\s*=\s*['"]([^'"]+)['"]""", re.M)


def _version_in_file(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _VERSION_ASSIGN.search(text)
    return match.group(1) if match else None


def folder_version(folder: Path) -> str | None:
    """The package version in a source folder (literal or hatchling dynamic)."""
    try:
        data = tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    version = data.get("project", {}).get("version")
    if isinstance(version, str):
        return version
    # Hatchling: [tool.hatch.version] path = "…/__init__.py"
    path = data.get("tool", {}).get("hatch", {}).get("version", {}).get("path")
    if isinstance(path, str):
        return _version_in_file(folder / path)
    return None


def is_git_folder(folder: Path) -> bool:
    return (folder / ".git").exists()


def source_files(folder: Path) -> list[str]:
    """The files of a folder without git, as relative paths.

    It follows links that stay inside the folder and skips links that leave it.
    It skips dot files, caches, builds and logs.
    """
    top = folder.resolve()
    found = []
    for root, dirs, files in os.walk(folder, followlinks=True):
        here = Path(root)
        rel = here.relative_to(folder).parts
        # The real folders on the way down: a link back to one of them is a loop.
        chain = {(folder / Path(*rel[:i])).resolve() for i in range(len(rel) + 1)}
        kept = []
        for name in sorted(dirs):
            real = (here / name).resolve()
            if name.startswith(".") or name in SKIP_DIRS or name.endswith(".egg-info"):
                continue
            if real.is_relative_to(top) and real not in chain:
                kept.append(name)
        dirs[:] = kept
        for name in files:
            real = (here / name).resolve()
            if name.startswith(".") or name.endswith(SKIP_SUFFIXES):
                continue
            if real.is_file() and real.is_relative_to(top):
                found.append((here / name).relative_to(folder).as_posix())
    return sorted(found)


def content_id(folder: Path) -> str:
    """A hash of the source files. It stands in for the commit of a folder without git."""
    digest = hashlib.sha256()
    for rel in source_files(folder):
        digest.update(rel.encode() + b"\0" + (folder / rel).read_bytes() + b"\0")
    return digest.hexdigest()


_TAG_AT = re.compile(r"^([0-9a-f]+)\s+refs/tags/(v?\d+(?:\.\d+)*)(?:\^{})?$", re.I)


def _tag_version(raw: str) -> tuple[tuple[int, ...], str]:
    number = raw[1:] if raw.lower().startswith("v") else raw
    return tuple(int(part) for part in number.split(".")), number


def _release_tags(out: str) -> list[tuple[str, str]]:
    """Pairs of (commit, dotted version) from `git ls-remote --tags` lines."""
    found: list[tuple[str, str]] = []
    for line in out.splitlines():
        match = _TAG_AT.match(line.strip())
        if not match:
            continue
        _, number = _tag_version(match.group(2))
        found.append((match.group(1), number))
    return found


def _best_version(tags: list[tuple[str, str]], commit: str | None = None) -> str | None:
    best: tuple[int, ...] | None = None
    chosen: str | None = None
    for tag_commit, number in tags:
        if commit is not None and tag_commit != commit:
            continue
        key, _ = _tag_version(number)
        if best is None or key > best:
            best, chosen = key, number
    return chosen


def version_at_commit(spec: str, commit: str, timeout: float = 3.0) -> str | None:
    """The release version of tags that point at commit, or None.

    `git ls-remote --tags` lists lightweight tags and the peeled commit of annotated
    tags (`refs/tags/vX.Y.Z^{}`). Only tags whose object is `commit` count. When
    several match, the highest dotted version wins. A missing older tag (for
    example only `v0.3.0` exists, no `v0.2.0`) does not block reading the version
    at HEAD. When no release tag points at commit, callers may fall back to the
    highest remote release tag.
    """
    out = git(["ls-remote", "--tags", spec], timeout)
    if not out or not commit:
        return None
    return _best_version(_release_tags(out), commit)


def highest_release_version(spec: str, timeout: float = 3.0) -> str | None:
    """The highest `vX.Y.Z` / `X.Y.Z` tag on the remote, or None."""
    out = git(["ls-remote", "--tags", spec], timeout)
    if not out:
        return None
    return _best_version(_release_tags(out))


def latest(source: Source, timeout: float = 3.0) -> Latest:
    """The newest commit and version at the source. Raise SourceError."""
    if source.kind == "folder":
        folder = Path(source.spec)
        if not (folder / "pyproject.toml").is_file():
            raise SourceError(
                f"{folder} does not hold the memory source.",
                "Run `memory update --source PATH` with the folder you installed memory from.",
            )
        if is_git_folder(folder):
            commit = git(["-C", str(folder), "rev-parse", "HEAD"], timeout)
        else:
            commit = content_id(folder)
        return Latest(commit, folder_version(folder))
    out = git(["ls-remote", source.spec, "HEAD"], timeout)
    if not out:
        raise SourceError(
            f"Could not reach {source.spec}.",
            "Check the network and the URL. Then run `memory update` again.",
        )
    commit = out.split()[0]
    tags_out = git(["ls-remote", "--tags", source.spec], timeout) or ""
    tags = _release_tags(tags_out)
    version = _best_version(tags, commit) or _best_version(tags)
    return Latest(commit, version)


def dirty(folder: Path) -> bool:
    if not is_git_folder(folder):
        return False
    return bool(git(["-C", str(folder), "status", "--porcelain", "--untracked-files=no"]))


def is_newer(source: Source, version: str, commit: str | None, found: Latest) -> bool:
    """True when the source holds a newer memory than the installed one."""
    if is_behind(version, found.version):
        return True
    if not commit or not found.commit or commit == found.commit:
        return False
    if source.kind == "git" or not is_git_folder(Path(source.spec)):
        return True
    # A folder moved back to an older commit is not an update.
    check = ["-C", source.spec, "merge-base", "--is-ancestor", commit, found.commit]
    return git(check) is not None


def describe(version: str | None, commit: str | None) -> str:
    short = f"({commit[:7]})" if commit else ""
    return " ".join(part for part in (version, short) if part) or "unknown"


def ref_tag(commit: str | None) -> str:
    """A short `@hash` suffix for status, like uv's display. Empty when unknown."""
    return f" @{commit[:7]}" if commit else ""


_GITHUB_SPEC = re.compile(
    r"(?:https?://github\.com/|git@github\.com:|ssh://git@github\.com/)"
    r"([^/]+)/([^/]+?)(?:\.git)?/?$",
    re.I,
)


def github_compare_url(spec: str, old: str, new: str) -> str | None:
    """A GitHub compare link for two commits, or None when the source is not GitHub."""
    if not old or not new:
        return None
    match = _GITHUB_SPEC.match(spec.strip())
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    return f"https://github.com/{owner}/{repo}/compare/{old[:7]}...{new[:7]}"


def local_git_path(source: Source) -> Path | None:
    """A local git folder for this source, when subjects can be read without the network."""
    if source.kind == "folder":
        folder = Path(source.spec)
        return folder if is_git_folder(folder) else None
    if source.spec.startswith("file:"):
        folder = Path(unquote(urlparse(source.spec).path))
        return folder if is_git_folder(folder) else None
    return None


def commit_subjects(folder: Path, old: str, new: str, limit: int = 20) -> list[str]:
    """Commit subjects in old..new, newest last omitted; empty when git cannot say."""
    out = git(
        ["-C", str(folder), "log", "--format=%s", f"{old}..{new}", f"-{limit}"],
        timeout=5.0,
    )
    return out.splitlines() if out else []


def change_lines(source: Source, old: str | None, new: str | None) -> list[str]:
    """What changed between two refs: local subjects, or a GitHub compare URL."""
    if not old or not new or old == new:
        return []
    folder = local_git_path(source)
    if folder is not None:
        subjects = commit_subjects(folder, old, new)
        if subjects:
            return subjects
    url = github_compare_url(source.spec, old, new)
    return [url] if url else []


# --- the cached check for the session start -------------------------------------------


def _cache_path() -> Path:
    return cache_dir() / CACHE


def save_check(source: Source, version: str, commit: str | None, found: Latest, newer: bool):
    record = {
        "checked": stamp(now()),
        "source": source.spec,
        "installed": [version, commit],
        "found_commit": found.commit,
        "newer": newer,
        "from": describe(version, commit),
        "to": describe(found.version, found.commit),
    }
    _write_cache(record)


def _write_cache(record: dict) -> None:
    with contextlib.suppress(OSError):
        _cache_path().parent.mkdir(parents=True, exist_ok=True)
        _cache_path().write_text(json.dumps(record) + "\n", encoding="utf-8")


def _cached(source: Source, version: str, commit: str | None) -> tuple[dict, bool]:
    """The cache for this install, and whether it is fresh. Never raises."""
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        if data.get("source") != source.spec or data.get("installed") != [version, commit]:
            return {}, False
        age = now() - parse_time(str(data["checked"]))
    except (OSError, ValueError, KeyError, TypeError):
        return {}, False
    limit = FRESH_AFTER_FAILURE if data.get("failed") else FRESH
    return data, timedelta(0) <= age < limit


def refresh(source: Source, version: str, commit: str | None, timeout: float) -> dict:
    try:
        found = latest(source, timeout)
    except SourceError:
        found = None
    if found is None or (source.kind == "folder" and found.version is None):
        record = {"checked": stamp(now()), "source": source.spec, "failed": True}
        record |= {"installed": [version, commit], "newer": False}
        _write_cache(record)
        return record
    save_check(source, version, commit, found, is_newer(source, version, commit, found))
    return _cached(source, version, commit)[0]


def update_line(background: bool = True) -> str | None:
    """One line when the source is newer than this tool. Silent offline. Never raises."""
    try:
        source, commit = installed(None)
        if source is None or source.editable:
            return None
        version = current_version()
        data, fresh = _cached(source, version, commit)
        if not fresh:
            if source.kind == "git" and background:
                # Mark the check as started, so the next sessions do not start it again.
                _write_cache(
                    {
                        **data,
                        "checked": stamp(now()),
                        "source": source.spec,
                        "installed": [version, commit],
                        "failed": True,
                    }
                )
                spawn_check()
            else:
                data = refresh(source, version, commit, 1.0 if source.kind == "folder" else 3.0)
        if data.get("newer"):
            return (
                f"memory: a newer memory is at {source.spec} ({data['from']} -> {data['to']}). "
                "Tell the owner. `memory update` installs it."
            )
    except Exception:
        return None
    return None


def pending_change_lines() -> list[str]:
    """Subjects or a compare URL when the cached check says the source is newer.

    Call after update_line so a stale cache has been refreshed. Never raises.
    """
    try:
        source, commit = installed(None)
        if source is None or source.editable:
            return []
        data, _ = _cached(source, current_version(), commit)
        if not data.get("newer"):
            return []
        found = data.get("found_commit")
        if not isinstance(found, str):
            return []
        return change_lines(source, commit, found)
    except Exception:
        return []
