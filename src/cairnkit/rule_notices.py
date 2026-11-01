"""An agent's change to a rule that binds is allowed, and it is never silent.

The change is correct only when the owner stated it in the same session. The tool cannot prove
that, so it prints a line at once and names the rule once in the next load. It is a notice: it
refuses nothing and queues nothing. The file holds ids only, so a purge leaves no text in it.
"""

from __future__ import annotations

import contextlib
import json
import os

from cairnkit.memory import Memory
from cairnkit.selection import DATA_LABEL, clean, owner_rule
from cairnkit.skills import running_tool

PENDING = ".rule-notices"
TELL = "Tell the owner now. This change is correct only if the owner stated it in this session."


def _line(by: str, fact_id: str, what: str, text: object) -> str:
    named = f" ({DATA_LABEL}): {clean(text)}" if text else ""
    return f"{clean(by)} changed rule {fact_id} ({clean(what)}){named}. {TELL}"


def note_change(memory: Memory, state: dict, what: str) -> None:
    """After a write: print the line and keep the id, when an agent changed a rule that binds."""
    agent = running_tool()
    if not agent or state.get("kind") != "rule" or not owner_rule(state):
        return
    by = f"agent:{agent}"
    print("notice: " + _line(by, state["id"], what, state.get("text")))
    record = {"id": state["id"], "what": what, "by": by}
    with contextlib.suppress(OSError), (memory.dir / PENDING).open("a", encoding="utf-8") as out:
        out.write(json.dumps(record) + "\n")


def take_lines(memory: Memory) -> list[str]:
    """The lines for this load. Once taken they are gone. The rename keeps a later write safe."""
    path = memory.dir / PENDING
    taken = path.with_name(PENDING + ".taken")
    try:
        os.replace(path, taken)
        raw = taken.read_text(encoding="utf-8", errors="replace")
        taken.unlink()
    except OSError:
        return []
    lines = []
    for row in raw.splitlines():
        with contextlib.suppress(ValueError, KeyError, TypeError, AttributeError):
            record = json.loads(row)
            state = memory.states.get(record["id"]) or {}
            lines.append(
                "memory: " + _line(record["by"], record["id"], record["what"], state.get("text"))
            )
    return lines
