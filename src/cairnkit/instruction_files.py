"""The hand-written instruction files, and the rule lines that already live in them.

A text lives in an instruction file when its words, in the same order (lower
case, punctuation and markup left out), are the words of a run of whole
sentences of one item there. Where the sentences break inside that run does
not count, so "Do X. Do Y." matches "Do X; do Y.", but the run must start and
end at a sentence edge, so "Use uv." does not match "Use uv for Python." An
item is a bullet or a paragraph, with its wrapped lines joined.

The block that `memory instructions` writes (between its marker lines) is the
tool's own text, not a home, so it is left out. So is an HTML comment, also
one over many lines. A start marker or a comment with no end runs to the end
of the file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from cairnkit.candidates import BULLET_RE, FENCE_RE, HEADING_RE
from cairnkit.instructions import PAIRS

FILES = ("AGENTS.md", "CLAUDE.md", "CLAUDE.local.md")
BLOCK_ENDS = dict(PAIRS)  # the start marker of memory's block, and its end marker

SENTENCE_END_RE = re.compile(r"[.!?]+[*_`'\")\]]*(?:\s+|$)")
# A Markdown link or image keeps its text, not its target. An HTML tag or comment goes.
LINK_TEXT_RE = re.compile(r"!?\[([^\]]*)\]")
TAG_RE = re.compile(r"<!--.*?-->|</?[A-Za-z](?:[^>\"']|\"[^\"]*\"|'[^']*')*>")
COMMENT_RE = re.compile(r"<!--.*?-->")

Sentences = tuple[tuple[str, ...], ...]


def _target_end(text: str, start: int) -> int | None:
    """Where a link target that starts at `start` ends: `[ref]`, or `(...)` with nested parens."""
    if text.startswith("[", start):
        close = text.find("]", start)
        return close + 1 if close != -1 else None
    if not text.startswith("(", start):
        return None
    depth = 0
    for at in range(start, len(text)):
        depth += {"(": 1, ")": -1}.get(text[at], 0)
        if depth == 0:
            return at + 1
    return None


def _drop_link_targets(text: str) -> str:
    out, pos = [], 0
    while match := LINK_TEXT_RE.search(text, pos):
        end = _target_end(text, match.end())
        if end is None:
            out.append(text[pos : match.end()])
            pos = match.end()
        else:
            out.append(text[pos : match.start()] + match.group(1))
            pos = end
    return "".join(out) + text[pos:]


def sentences(text: str) -> Sentences:
    """The words of each sentence, in order. Link targets and HTML tags are not words."""
    text = TAG_RE.sub("", _drop_link_targets(text))
    parts = (tuple(re.findall(r"[a-z0-9]+", s.lower())) for s in SENTENCE_END_RE.split(text))
    return tuple(p for p in parts if p)


@dataclass(frozen=True)
class Item:
    file: str
    line: int
    sentences: Sentences


def _items(file: str, text: str) -> list[Item]:
    found: list[tuple[int, list[str]]] = []
    open_item = in_code = in_comment = False
    block_end = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line in BLOCK_ENDS:
            block_end = BLOCK_ENDS[line]
        if block_end:
            block_end, open_item = (None if line == block_end else block_end), False
            continue
        if in_comment:
            if "-->" not in raw:
                open_item = False
                continue
            raw, in_comment = raw.split("-->", 1)[1], False
        elif FENCE_RE.match(raw):
            in_code, open_item = not in_code, False
            continue
        elif in_code:
            continue
        raw = COMMENT_RE.sub("", raw)
        if "<!--" in raw:
            raw, in_comment = raw.split("<!--", 1)[0], True
        line = raw.strip()
        if not TAG_RE.sub("", line).strip() or HEADING_RE.match(line) or line[0] == "|":
            open_item = False
            continue
        bullet = BULLET_RE.match(raw)
        if bullet or not open_item:
            found.append((number, [bullet.group(1) if bullet else line]))
            open_item = True
        else:
            found[-1][1].append(line)
    return [Item(file, number, sentences(" ".join(lines))) for number, lines in found]


def items(root: Path) -> list[Item]:
    """Every item of the instruction files in a checkout, in file order."""
    found: list[Item] = []
    for name in FILES:
        try:
            text = (root / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found += _items(name, text)
    return found


def home(found: list[Item], text: str) -> Item | None:
    """The first item that holds the text, or None."""
    want = tuple(word for sentence in sentences(text) for word in sentence)
    if not want:
        return None
    for item in found:
        have = item.sentences
        for start in range(len(have)):
            words: tuple[str, ...] = ()
            for sentence in have[start:]:
                words += sentence
                if len(words) >= len(want):
                    break
            if words == want:
                return item
    return None
