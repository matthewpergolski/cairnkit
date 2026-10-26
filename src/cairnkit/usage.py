"""When was a fact last looked up on purpose? It feeds the rank in `memory load`.

`memory show` and `memory search` record the facts they print. `memory load`
does not: a loaded fact was only offered, not used, and counting it would
lock the top of the ranking in place.

The record is append only. Each writer has `<memory>/.usage/<writer>.log`, and
each line is a time, a tab and a fact id. The reader keeps the latest time for
each id over all files. `compact` rewrites a long file to one line per id. It
is safe to skip, and the whole folder is safe to delete. A failure to write is
ignored.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterable
from datetime import datetime

from cairnkit.clock import parse_time, stamp
from cairnkit.memory import Memory
from cairnkit.paths import writer_name

FOLDER = ".usage"
COMPACT_AT = 2000  # lines in one file


def _lines(path) -> Iterable[tuple[str, datetime]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for raw in text.splitlines():
        when, _, fact_id = raw.partition("\t")
        try:
            yield fact_id.strip(), parse_time(when)
        except ValueError:
            continue


def last_used(memory: Memory) -> dict[str, datetime]:
    """Return {fact id: latest time any writer looked it up}."""
    found: dict[str, datetime] = {}
    try:
        files = sorted((memory.dir / FOLDER).glob("*.log"))
    except OSError:
        return found
    for path in files:
        for fact_id, moment in _lines(path):
            if fact_id and (fact_id not in found or moment > found[fact_id]):
                found[fact_id] = moment
    return found


def record(memory: Memory, ids: Iterable[str], moment: datetime) -> None:
    """Note that these facts were looked up now. Never raises."""
    with contextlib.suppress(Exception):
        known = [fact_id for fact_id in ids if fact_id in memory.states]
        if not known:
            return
        folder = memory.dir / FOLDER
        folder.mkdir(exist_ok=True)
        payload = "".join(f"{stamp(moment)}\t{fact_id}\n" for fact_id in known)
        with (folder / f"{writer_name(memory.project.root)}.log").open("a", encoding="utf-8") as fh:
            fh.write(payload)


def compact(memory: Memory, threshold: int | None = None) -> None:
    """Rewrite each long file to its latest line per id. Safe to skip. Never raises."""
    limit = COMPACT_AT if threshold is None else threshold
    with contextlib.suppress(Exception):
        for path in sorted((memory.dir / FOLDER).glob("*.log")):
            if len(path.read_text(encoding="utf-8").splitlines()) <= limit:
                continue
            latest: dict[str, datetime] = {}
            for fact_id, moment in _lines(path):
                if fact_id in memory.states and (fact_id not in latest or moment > latest[fact_id]):
                    latest[fact_id] = moment
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for fact_id, moment in sorted(latest.items(), key=lambda kv: kv[1]):
                    fh.write(f"{stamp(moment)}\t{fact_id}\n")
            os.replace(tmp, path)
