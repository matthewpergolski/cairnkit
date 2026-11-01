"""`memory repair`: settle what `memory check` finds, with no hand edit and no purge.

A fact file is append-only, so a damaged line stays on disk. A row in `repairs.jsonl` says that its
bytes are known, so the load and the check stop counting them. Each line of the output keeps the
plain words of the damaged line, so that an agent can write the fact again, and it prints no value.
A new bad line has other bytes, so a repair never hides it. A repair does not settle a value that looks
secret: `memory check` names it until `memory purge` removes it.
"""

from __future__ import annotations

from cairnkit.check import RecordIndex, check_records, record_problems, writer_differs
from cairnkit.clock import now, stamp
from cairnkit.config import repair_config
from cairnkit.memory import Memory
from cairnkit.paths import writer_name
from cairnkit.secretscan import mask, readable
from cairnkit.selection import clean
from cairnkit.store import REPAIRS, append_records, fact_files, repaired_lines, scan

SHOWN = 300


def run_repair(memory: Memory) -> int:
    located, bad = scan(fact_files(memory.dir))
    done = repaired_lines(memory.dir, located)
    index = RecordIndex.of(located)
    writer = writer_name(memory.project.root)
    at = stamp(now())
    records: list[dict] = []

    def settle(path, line: int, sha: str, why: str, text: str) -> None:
        held = clean(readable(text, memory.env))[:SHOWN]
        print(f"{path.name}:{line}: {clean(mask(why, memory.env))}\n  It held: {held}")
        # No text from the line goes in the record: the line can hold a secret, and purge must find
        # each copy by its id.
        records.append(
            {
                "file": path.name,
                "sha": sha,
                "line": line,
                "at": at,
                "writer": writer,
            }
        )

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
            rec = item.record
            text = str(rec.get("text") or rec.get("reason") or "")
            settle(item.path, item.line, item.sha, "; ".join(why), text)
    # Two files can hold the same bad bytes, and a line can appear twice. One record covers each.
    unique = {(r["file"], r["sha"]): r for r in records}
    if unique:
        append_records(memory.dir / REPAIRS, list(unique.values()))
        print(
            f"Recorded {len(unique)} line(s). The bytes stay in the file. Write again what is true."
        )
    fixed = repair_config(memory.dir, memory.env)
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
