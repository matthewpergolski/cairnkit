"""Read and append fact files. The only rewrite is `purge`."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from cairnkit import deadline

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None


# Only a writer that hangs holds a lock this long: a write takes milliseconds.
LOCK_WAIT = 5.0
# One lock for each write of a fact file. A purge replaces a file, so a lock on the file itself
# would leave a writer that holds the old file writing to nothing.
WRITE_LOCK = ".write.lock"
# A write still waits this long after git used the whole budget: the fact comes first.
WRITE_LOCK_FLOOR = 1.0


class LockBusy(Exception):
    """Another process held a lock past the limit. The write did not happen."""


def _lock(fh, path: Path, floor: float = 0) -> None:
    """Take the lock, or raise LockBusy at the limit. A session must not wait forever."""
    if fcntl is None:
        return
    wait = max(min(LOCK_WAIT, deadline.left()), floor)
    end = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as exc:
            if time.monotonic() >= end:
                raise LockBusy(
                    f"{path.name} is locked by another process, and the wait ended after "
                    f"{wait:.0f} s. Nothing was written. Run the same command again."
                ) from exc
        time.sleep(0.02)


@dataclass
class Located:
    record: dict
    path: Path
    line: int
    sha: str = ""


@dataclass
class BadLine:
    """A line that the code cannot use. A file that cannot be read has no sha, and no repair."""

    path: Path
    line: int
    why: str
    text: str = ""
    sha: str = ""

    @property
    def message(self) -> str:
        return f"{self.path.name}:{self.line}: {self.why}" if self.sha else self.why


def fact_files(memdir: Path) -> list[Path]:
    return sorted((memdir / "facts").glob("*.jsonl"))


# The field types that the code after the read relies on. Null counts as absent.
_TEXT_FIELDS = (
    "id", "text", "kind", "area", "status", "scope", "basis", "source", "summary", "writer",
    "happened_at", "learned_at", "expires_at", "until_branch_merged", "branch_tip", "at",
    "superseded_by", "held_by", "file", "sha",
)  # fmt: skip
_NEEDS = {
    "fact": ("id", "text"),
    "change": ("id",),
    "tombstone": ("id",),
    "repair": ("file", "sha"),
}


def _links_ok(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(link, dict) and isinstance(link.get("id"), str) for link in value
    )


def unusable(record: dict) -> str | None:
    """Why the code cannot use this record, or None. Schema problems are for `memory check`.

    A record that is odd but usable must still load: a true fact stays in the load.
    """
    kind = record.get("type")
    if not isinstance(kind, str) or kind not in _NEEDS:
        return f"type {kind!r} is not known"
    for name in _NEEDS[kind]:
        if name not in record:
            return f"a {kind} needs {name}"
    for name in _TEXT_FIELDS:
        if record.get(name) is not None and not isinstance(record[name], str):
            return f"{name} must be a string"
    if any(record[name] is None for name in _NEEDS[kind]):
        return f"a {kind} needs {' and '.join(_NEEDS[kind])}"
    for name in ("links", "add_links"):
        if record.get(name) is not None and not _links_ok(record[name]):
            return f"{name} must be a list of links"
    if record.get("tags") is not None and not isinstance(record["tags"], list):
        return "tags must be a list"
    return None


def _line_sha(raw: bytes) -> str:
    return hashlib.sha1(raw.strip()).hexdigest()[:16]


def scan(files: list[Path]) -> tuple[list[Located], list[BadLine]]:
    """Parse every line. Return the records and the bad lines, repaired ones too.

    This reads bytes, because a crash can cut a file inside a character. A bad byte loses its own
    line. Only a newline ends a line, because a text can hold U+2028 and JSON keeps it as it is.
    """
    found: list[Located] = []
    bad: list[BadLine] = []
    for path in files:
        try:
            lines = path.read_bytes().split(b"\n")
        except OSError as exc:
            bad.append(BadLine(path, 0, f"{path}: cannot read: {exc}"))
            continue
        for number, raw in enumerate(lines, start=1):
            if not raw.strip():
                continue
            sha = _line_sha(raw)
            text = raw.decode("utf-8", errors="replace")
            try:
                record = json.loads(raw.decode("utf-8"))
                why = unusable(record) if isinstance(record, dict) else None
                if not isinstance(record, dict):
                    why = "a record must be a JSON object"
            except UnicodeDecodeError:
                why = "not valid UTF-8"
            except json.JSONDecodeError as exc:
                why = f"not valid JSON: {exc.msg}"
            if why:
                bad.append(BadLine(path, number, why, text, sha))
            else:
                found.append(Located(record, path, number, sha))
    return found, bad


def repaired_lines(located: list[Located]) -> set[tuple[str, str]]:
    """(file name, line hash) of each line that a `repair` record settled."""
    return {
        (item.record["file"], item.record["sha"])
        for item in located
        if item.record.get("type") == "repair"
    }


def read_located(files: list[Path]) -> tuple[list[Located], list[str]]:
    """Return the records, and one message per bad line that no repair settled."""
    found, bad = scan(files)
    done = repaired_lines(found)
    return found, [b.message for b in bad if (b.path.name, b.sha) not in done]


def read_records(files: list[Path]) -> tuple[list[dict], list[str]]:
    located, errors = read_located(files)
    return [item.record for item in located], errors


def encode(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def append_records(path: Path, records: list[dict]) -> None:
    """Append records as JSON lines in one write. Earlier bytes never change."""
    payload = "".join(encode(r) + "\n" for r in records).encode("utf-8")
    with locked(path.parent / WRITE_LOCK, WRITE_LOCK_FLOOR), path.open("ab") as fh:
        size = fh.seek(0, os.SEEK_END)
        if size:
            with path.open("rb") as check:
                check.seek(size - 1)
                if check.read(1) != b"\n":
                    payload = b"\n" + payload
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())


_held: set[Path] = set()


@contextlib.contextmanager
def locked(path: Path, floor: float = 0) -> Iterator[None]:
    """Hold an exclusive lock on a lock file while the block runs (no lock on Windows).

    A block inside a block of the same lock does not lock again, because flock would wait on itself.
    """
    if path in _held:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as fh:
        _lock(fh, path, floor)
        _held.add(path)
        try:
            yield
        finally:
            _held.discard(path)
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)


def write_lock(memdir: Path):
    """The lock of every write to the fact files of one memory."""
    return locked(memdir / "facts" / WRITE_LOCK, WRITE_LOCK_FLOOR)


def drop_id(memdir: Path, fact_id: str) -> int:
    """Rewrite each fact file without the lines for fact_id. Return how many lines went.

    The files are read inside the lock, so a fact that an add wrote a moment ago stays.
    """

    def is_gone(raw: bytes) -> bool:
        """A line goes when it parses to that id, or when it does not parse and holds the id."""
        try:
            record = json.loads(raw.decode("utf-8"))
            return isinstance(record, dict) and record.get("id") == fact_id
        except ValueError:
            return fact_id.encode() in raw

    return _drop_lines(memdir, is_gone)


def drop_line(memdir: Path, sha: str) -> int:
    """Rewrite each fact file without the lines with this hash, the hash that `scan` gives."""
    return _drop_lines(memdir, lambda raw: _line_sha(raw) == sha)


def _drop_lines(memdir: Path, is_gone: Callable[[bytes], bool]) -> int:
    with write_lock(memdir):
        return sum(_rewrite(path, is_gone) for path in fact_files(memdir))


def _rewrite(path: Path, is_gone: Callable[[bytes], bool]) -> int:
    lines = list(io.BytesIO(path.read_bytes()))
    kept = [raw for raw in lines if not is_gone(raw)]
    if len(kept) == len(lines):
        return 0
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".purge-")
    with os.fdopen(fd, "wb") as fh:
        fh.writelines(kept)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    return len(lines) - len(kept)
