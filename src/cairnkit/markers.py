"""The start and end markers of a block that memory writes into another file."""

from __future__ import annotations


def state(text: str, start: str, end: str) -> str:
    """Return missing (no marker), ok (one start, then one end) or broken."""
    if start not in text and end not in text:
        return "missing"
    if text.count(start) == 1 and text.count(end) == 1 and text.find(start) < text.find(end):
        return "ok"
    return "broken"


def broken_message(path, command: str) -> str:
    return (
        f"error: {path} has a lost marker or two memory blocks. Nothing changed in it. "
        f"Fix the markers by hand, then run `{command}` again."
    )


def find(text: str, pairs) -> tuple[str, tuple[str, str]]:
    """The state of the block and the marker pair it uses.

    `pairs` lists the current (start, end) pair first, then older names. Markers
    of two pairs in one text are two blocks: broken.
    """
    used = [p for p in pairs if p[0] in text or p[1] in text]
    if not used:
        return "missing", pairs[0]
    if len(used) > 1:
        return "broken", used[0]
    return state(text, *used[0]), used[0]
