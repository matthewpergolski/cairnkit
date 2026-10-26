"""Candidate facts from prose notes, for `memory migrate`.

This module reads text and makes a worklist. It has no model and writes no
fact. A person or an agent reads the worklist and adds the facts it wants.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

MAX_FACT_CHARS = 400

BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(\S.*)$")
DATED_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
DATE_IN_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
SUPERSEDED_RE = re.compile(r"\(\s*superseded\b[^)]*\)\s*$", re.IGNORECASE)
HELD_BY_RE = re.compile(r"\(\s*held by\s+`?([^`)]+?)`?\s*(?:[:;,][^)]*)?\)", re.IGNORECASE)

# Words in a file name or a heading, checked in this order.
KIND_WORDS = (
    ("decision", "decision"),
    ("trap", "trap"),
    ("gotcha", "trap"),
    ("pitfall", "trap"),
    ("lesson", "lesson"),
    ("learned", "lesson"),
    ("log", "event"),
    ("event", "event"),
    ("history", "event"),
)


@dataclass
class Candidate:
    file: str
    line: int
    heading: str
    text: str
    kind: str
    happened_at: str | None = None
    hint: str | None = None
    held_by: str | None = None
    too_long: bool = False
    worktree: str | None = None  # the worktree whose own old notes hold this line
    origin: str | None = None  # the file that holds it, when it is not in the main notes

    @property
    def tier(self) -> str:
        """`likely` for a decision, trap, lesson, event or brief line; `maybe` for the rest.

        A line found only in a worktree's own old notes is `worktree-only`.
        """
        if self.worktree:
            return "worktree-only"
        return (
            "likely" if self.kind != "fact" or PurePosixPath(self.file).stem == "brief" else "maybe"
        )


@dataclass
class Counts:
    """Every non-blank line goes into exactly one of these."""

    lines: int = 0
    candidates: int = 0
    continuation: int = 0
    headings: int = 0
    code: int = 0
    table: int = 0
    other: int = 0
    instructions: int = 0  # a candidate that an instruction file already holds

    def add(self, other: Counts) -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))


def kind_for(file: str, heading: str) -> str:
    """Suggest a fact kind from the file name, then the heading. `fact` when unsure."""
    for text in (file.lower(), heading.lower()):
        for word, kind in KIND_WORDS:
            if word in text:
                return kind
    return "fact"


def _make(file: str, number: int, heading: str, text: str) -> Candidate:
    found = DATED_RE.match(text) or DATE_IN_RE.search(text)
    cand = Candidate(
        file=file,
        line=number,
        heading=heading,
        text=text,
        kind=kind_for(file, heading),
        happened_at=found.group(1) if found else None,
        too_long=len(text) > MAX_FACT_CHARS,
    )
    held = HELD_BY_RE.search(text)
    if held:
        cand.hint, cand.held_by = "held_by", held.group(1).strip()
    elif SUPERSEDED_RE.search(text):
        cand.hint = "superseded"
    return cand


def scan_text(file: str, text: str) -> tuple[list[Candidate], Counts]:
    """Return the candidates in one note, and the counts of its lines by kind."""
    found: list[Candidate] = []
    counts = Counts()
    heading = ""
    in_code = False
    in_front = False
    open_item = False  # the last non-blank line was a bullet or its continuation
    lines = text.splitlines()
    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if not line.strip():
            open_item = False
            continue
        counts.lines += 1
        stripped = line.strip()
        if number == 1 and stripped == "---":
            in_front = True
            counts.other += 1
            continue
        if in_front:
            counts.other += 1
            in_front = stripped != "---"
            continue
        if FENCE_RE.match(line):
            in_code = not in_code
            counts.code += 1
            open_item = False
            continue
        if in_code:
            counts.code += 1
            continue
        match = HEADING_RE.match(line)
        if match:
            heading = match.group(1)
            counts.headings += 1
            open_item = False
            continue
        if stripped.startswith("|"):
            counts.table += 1
            open_item = False
            continue
        bullet = BULLET_RE.match(line)
        if bullet or DATED_RE.match(stripped):
            found.append(_make(file, number, heading, bullet.group(1) if bullet else stripped))
            counts.candidates += 1
            open_item = True
        elif open_item and line[:1] in (" ", "\t"):
            last = found[-1]
            joined = _make(file, last.line, heading, f"{last.text} {stripped}")
            found[-1] = joined
            counts.continuation += 1
        else:
            counts.other += 1
            open_item = False
    return found, counts
