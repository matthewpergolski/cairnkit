"""Read and append fact files. The only rewrite is `purge`."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None


@dataclass
class Located:
    record: dict
    path: Path
    line: int


def fact_files(memdir: Path) -> list[Path]:
    return sorted((memdir / "facts").glob("*.jsonl"))


def read_located(files: list[Path]) -> tuple[list[Located], list[str]]:
    """Parse every line. Return the records and one message per bad line."""
    found: list[Located] = []
    errors: list[str] = []
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"{path}: cannot read: {exc}")
            continue
        for number, raw in enumerate(lines, start=1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"{path.name}:{number}: not valid JSON: {exc.msg}")
                continue
            if not isinstance(record, dict):
                errors.append(f"{path.name}:{number}: a record must be a JSON object")
                continue
            found.append(Located(record, path, number))
    return found, errors


def read_records(files: list[Path]) -> tuple[list[dict], list[str]]:
    located, errors = read_located(files)
    return [item.record for item in located], errors


def encode(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def append_records(path: Path, records: list[dict]) -> None:
    """Append records as JSON lines in one write. Earlier bytes never change."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(encode(r) + "\n" for r in records).encode("utf-8")
    with path.open("ab") as fh:
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            size = fh.seek(0, os.SEEK_END)
            if size:
                with path.open("rb") as check:
                    check.seek(size - 1)
                    if check.read(1) != b"\n":
                        payload = b"\n" + payload
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold an exclusive lock on a lock file while the block runs (no lock on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as fh:
        if fcntl is not None:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)


def drop_id(path: Path, fact_id: str) -> int:
    """Rewrite one file without the lines for fact_id. Return how many lines went.

    A line goes when it parses to that id, or when it does not parse and holds the id.
    """
    kept: list[str] = []
    dropped = 0
    for raw in path.read_text(encoding="utf-8").splitlines(keepends=True):
        try:
            record = json.loads(raw)
            match = isinstance(record, dict) and record.get("id") == fact_id
        except json.JSONDecodeError:
            match = fact_id in raw
        if match:
            dropped += 1
        else:
            kept.append(raw)
    if dropped:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".purge-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(kept)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    return dropped
