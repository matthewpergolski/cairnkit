"""`memory repair`: settle what `memory check` finds, with no hand edit and no purge.

A fact file is append-only, so a damaged line stays on disk. A `repair` record says that its bytes
are known, so the load and the check stop counting them. Each line of the output keeps what can
be read of the damaged line, so that an agent can write the fact again. A new bad line has other
bytes, so a repair never hides it.
"""

from __future__ import annotations

from cairnkit.check import RecordIndex, check_records, record_problems, writer_differs
from cairnkit.clock import now, stamp
from cairnkit.config import repair_config
from cairnkit.memory import Memory
from cairnkit.paths import writer_name
from cairnkit.schema import validate_record
from cairnkit.secretscan import find_secrets
from cairnkit.selection import clean
from cairnkit.store import append_records, encode, fact_files, repaired_lines, scan

SHOWN = 300


def _shown(text: str) -> str:
    return "[hidden: it looks like a secret]" if find_secrets(text) else clean(text)[:SHOWN]


def run_repair(memory: Memory) -> int:
    located, bad = scan(fact_files(memory.dir))
    done = repaired_lines(located)
    index = RecordIndex.of(located)
    writer = writer_name(memory.project.root)
    at = stamp(now())
    records: list[dict] = []

    def settle(path, line: int, sha: str, why: str, text: str) -> None:
        print(f"{path.name}:{line}: {why}\n  It held: {_shown(text)}")
        record = {
            "type": "repair",
            "file": path.name,
            "sha": sha,
            "line": line,
            "why": why,
            "at": at,
            "writer": writer,
        }
        if not validate_record(record):
            records.append(record)

    for item in bad:
        if item.sha and (item.path.name, item.sha) not in done:
            settle(item.path, item.line, item.sha, item.why, item.text)
    for item in located:
        if (item.path.name, item.sha) in done:
            continue
        why = record_problems(item, index)
        if writer_differs(item):
            why.append(writer_differs(item))
        if why:
            settle(item.path, item.line, item.sha, "; ".join(why), encode(item.record))
    # Two files can hold the same bad bytes, and a line can appear twice. One record covers each.
    unique = {(r["file"], r["sha"]): r for r in records}
    if unique:
        append_records(memory.writer_file(writer), list(unique.values()))
        print(
            f"Recorded {len(unique)} line(s). The bytes stay in the file. Write again what is true."
        )
    fixed = repair_config(memory.dir)
    for line in fixed:
        print(line)
    memory.reload()
    errors, warnings = check_records(memory)
    left = errors + warnings
    for line in left:
        print(f"still open: {line}")
    if not unique and not fixed and not left:
        print("Nothing to repair.")
    return 1 if left else 0
