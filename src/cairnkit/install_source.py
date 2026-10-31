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
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse, urlsplit, urlunsplit

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
class Release:
    name: str
    version: str
    commit: str


def _git_key(spec: str) -> str:
    """Compare git remotes without a trailing ``.git`` spelling difference."""
    return spec[:-4] if spec.lower().endswith(".git") else spec


@dataclass(frozen=True)
class Source:
    """A folder path, or a git remote with the receipt pin parsed off.

    ``pin`` is only for ``label``. Equality ignores it and a trailing ``.git``,
    so a receipt pin and a recorded tag on the same remote are the same source.
    """

    spec: str  # an absolute folder path, or a git URL without the git+ prefix
    kind: str  # "folder" or "git"
    editable: bool = False
    pin: str | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.kind not in ("folder", "git"):
            raise ValueError(f"kind must be folder or git, not {self.kind!r}")
        if self.kind != "git":
            return
        clean, pin = _split_vcs(self.spec)
        if not self.spec or clean != self.spec or pin is not None:
            raise ValueError(f"git spec must be a clean remote, not {self.spec!r}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Source):
            return NotImplemented
        if self.kind != other.kind or self.editable != other.editable:
            return False
        if self.kind == "git":
            return _git_key(self.spec) == _git_key(other.spec)
        return self.spec == other.spec

    def __hash__(self) -> int:
        spec = _git_key(self.spec) if self.kind == "git" else self.spec
        return hash((self.kind, self.editable, spec))

    @property
    def label(self) -> str:
        if self.pin:
            return f"{self.spec} @ {self.pin} ({self.kind})"
        return f"{self.spec} ({self.kind})"


@dataclass(frozen=True)
class Latest:
    """What the check found. ``release`` stays after fetch replaces ``version``."""

    commit: str | None
    version: str | None
    release: Release | None = None


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
    """Stdout of a git command, or None when it fails.

    Empty stdout on exit 0 stays ``""``. A failed command is ``None``.
    """
    refuse_pinned_args(args)
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


def _query_pin(query: str) -> str | None:
    found = {key: value for key, value in parse_qsl(query, keep_blank_values=True)}
    for key in ("rev", "tag", "branch"):
        value = found.get(key)
        if value:
            return value
    return None


def _path_at_pin(path: str) -> tuple[str, str | None]:
    """Strip a trailing ``@ref`` from a URL path. Keep ``foo@bar/bare.git`` whole.

    A pin follows a path that already ends in ``.git``, even when the ref itself
    contains ``.git``. A ``@ref`` that is not a ``dir@…/.git`` directory path
    is also a pin, including ``@feature/foo``.
    """
    if "@" not in path:
        return path, None
    before, after = path.rsplit("@", 1)
    if not after:
        return path, None
    if before.lower().endswith(".git"):
        return before, after
    # ``…/foo@bar/bare.git`` is a directory name, not a pin.
    if "/" in after and after.lower().endswith(".git"):
        return path, None
    return before, after


def _protect_userinfo(url: str) -> str:
    """Percent-encode ``?`` and ``#`` in userinfo so urlsplit keeps the authority."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    slash = rest.find("/")
    authority = rest if slash < 0 else rest[:slash]
    tail = "" if slash < 0 else rest[slash:]
    if "@" not in authority:
        return url
    userinfo, _, hostport = authority.rpartition("@")
    safe = userinfo.replace("?", "%3F").replace("#", "%23")
    return f"{scheme}://{safe}@{hostport}{tail}"


def _restore_userinfo(netloc: str) -> str:
    """Undo only the userinfo escapes added by ``_protect_userinfo``."""
    if "@" not in netloc:
        return netloc
    userinfo, _, hostport = netloc.rpartition("@")
    userinfo = userinfo.replace("%3F", "?").replace("%23", "#")
    return f"{userinfo}@{hostport}"


def _split_scp(text: str) -> tuple[str, str | None]:
    """Split ``git@host:path`` pins without treating the user ``@`` as a pin."""
    colon = text.find(":")
    if colon < 0:
        return text, None
    head, rest = text[: colon + 1], text[colon + 1 :]
    fragment = ""
    if "#" in rest:
        rest, fragment = rest.split("#", 1)
    query_pin = None
    if "?" in rest:
        rest, query = rest.split("?", 1)
        query_pin = _query_pin(query)
    rest, path_pin = _path_at_pin(rest)
    if query_pin:
        pin = query_pin
    elif path_pin:
        pin = path_pin
    elif fragment and "=" not in fragment:
        pin = unquote(fragment)
    else:
        pin = None
    return head + rest, pin

def _split_vcs(text: str) -> tuple[str, str | None]:
    """Split a remote that has no ``git+`` prefix into ``(clean URL, pin)``.

    Query ``rev``, then ``tag``, then ``branch`` wins. Else a path ``@ref``.
    Else a fragment with no ``=``. Userinfo ``?`` / ``#`` and the ``git@host``
    user stay. A clean remote comes back unchanged.
    """
    if text.startswith("git@"):
        return _split_scp(text)
    if "://" not in text:
        return text, None
    parts = urlsplit(_protect_userinfo(text))
    path, path_pin = _path_at_pin(parts.path)
    query_pin = _query_pin(parts.query)
    fragment = parts.fragment
    if query_pin:
        pin = query_pin
    elif path_pin:
        pin = path_pin
    elif fragment and "=" not in fragment:
        pin = unquote(fragment)
    else:
        pin = None
    clean = urlunsplit((parts.scheme, _restore_userinfo(parts.netloc), path, "", ""))
    return clean, pin


def assert_clean(remote: str) -> str:
    """Raise when ``remote`` still carries a pin. Userinfo may contain ``?`` or ``#``."""
    clean, pin = _split_vcs(remote)
    if pin is not None or clean != remote:
        raise SourceError(
            f"Refusing to pass {remote} to git.",
            "This is a bug in memory update. Strip the rev from the URL before calling git.",
        )
    return remote


def refuse_pinned_args(args: list[str]) -> None:
    for arg in args:
        if "://" in arg or arg.startswith("git@"):
            assert_clean(arg)


def parse(spec: str, editable: bool = False) -> Source:
    text = spec.strip()
    if text.startswith("git+"):
        text = text[4:]
    if "://" in text or text.startswith("git@"):
        clean, pin = _split_vcs(text)
        if not clean:
            raise SourceError(
                "The git URL is empty.",
                "Run `memory update --source` with a git URL or a folder path.",
            )
        return Source(clean, "git", False, pin)
    return Source(str(Path(text).expanduser().resolve()), "folder", editable)


def install_spec(source: Source, release: Release | None) -> str:
    """The record URL and the uv reinstall hint. Never reads ``source.pin``."""
    if source.kind == "folder":
        return source.spec
    if release is None:
        return f"git+{source.spec}"
    return f"git+{source.spec}@{release.name}"


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


def write_record(source: Source, commit: str | None, version: str, release: Release | None) -> None:
    record = {
        "source": install_spec(source, release),
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


# Strict X.Y.Z or vX.Y.Z only. One-part, four-part, and date tags do not count.
_TAG_AT = re.compile(r"^([0-9a-f]+)\s+refs/tags/(v?\d+\.\d+\.\d+)(?:\^{})?$", re.I)


def _tag_version(raw: str) -> tuple[tuple[int, ...], str]:
    number = raw[1:] if raw.lower().startswith("v") else raw
    return tuple(int(part) for part in number.split(".")), number


def _choose_release(ls_remote_tags: str) -> Release | None:
    """The highest release tag in ``git ls-remote --tags`` output, or None.

    A peeled ``^{}`` line replaces the tag object. When ``v0.3.1`` and ``0.3.1``
    tie, the ``v`` name wins.
    """
    shas: dict[str, str] = {}
    peeled: set[str] = set()
    for line in ls_remote_tags.splitlines():
        stripped = line.strip()
        match = _TAG_AT.match(stripped)
        if not match:
            continue
        sha, name = match.group(1), match.group(2)
        if stripped.endswith("^{}"):
            shas[name] = sha
            peeled.add(name)
        elif name not in peeled:
            shas[name] = sha
    best_name: str | None = None
    best_key: tuple[int, ...] = ()
    for name in shas:
        key, _number = _tag_version(name)
        prefer_v = (
            best_name is not None
            and key == best_key
            and name.lower().startswith("v")
            and not best_name.lower().startswith("v")
        )
        if best_name is None or key > best_key or prefer_v:
            best_name, best_key = name, key
    if best_name is None:
        return None
    _key, number = _tag_version(best_name)
    return Release(best_name, number, shas[best_name])


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
    remote = source.spec
    tags_out = git(["ls-remote", "--tags", remote], timeout)
    if tags_out is None:
        raise SourceError(
            f"Could not reach {remote}.",
            "Check the network and the URL. Then run `memory update` again.",
        )
    release = _choose_release(tags_out)
    if release is not None:
        return Latest(release.commit, release.version, release)
    out = git(["ls-remote", remote, "HEAD"], timeout)
    if not out:
        raise SourceError(
            f"Could not reach {remote}.",
            "Check the network and the URL. Then run `memory update` again.",
        )
    return Latest(out.split()[0], None)


def dirty(folder: Path) -> bool:
    if not is_git_folder(folder):
        return False
    return bool(git(["-C", str(folder), "status", "--porcelain", "--untracked-files=no"]))


def is_newer(source: Source, version: str, commit: str | None, found: Latest) -> bool:
    """True when the source holds a newer memory than the installed one."""
    if is_behind(version, found.version):
        return True
    # An older release tag is not an update, even when its commit differs.
    if found.version is not None and is_behind(found.version, version):
        return False
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
