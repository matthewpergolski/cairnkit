"""When are two facts the same thing said twice?

Two facts are similar when they share at least 80 percent of their words
(Jaccard on the lower-case word sets). That test only flags. A pair is not
similar at all when the words that differ hold a number, a negation or one
side of an opposite pair, because one changed word can reverse the meaning.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import NamedTuple

NEAR = 0.8

# Words that can reverse or change a fact. `don` and `t` come from "don't" split at the quote.
NEGATIONS = {
    "not", "no", "never", "none", "nor", "cannot", "without", "don", "doesn", "didn", "isn",
    "aren", "wasn", "weren", "won", "can", "shouldn", "couldn", "wouldn", "haven", "hasn", "t",
}  # fmt: skip
OPPOSITES = {
    "enable", "enabled", "disable", "disabled", "allow", "allowed", "forbid", "forbidden",
    "always", "before", "after", "on", "off", "true", "false", "yes", "add", "remove",
    "start", "stop", "increase", "decrease", "with", "must", "may",
}  # fmt: skip


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _meaningful(word: str) -> bool:
    return any(ch.isdigit() for ch in word) or word in NEGATIONS or word in OPPOSITES


class Words(NamedTuple):
    """The word set of a text, and a count of its numbers, negations and opposites."""

    tokens: set[str]
    meaning: Counter[str]


def analyze(text: str) -> Words:
    found = re.findall(r"[a-z0-9]+", text.lower())
    return Words(set(found), Counter(w for w in found if _meaningful(w)))


def exact_key(text: str) -> tuple[frozenset[str], frozenset[tuple[str, int]]]:
    """Two texts are an exact repeat when this key is the same."""
    words = analyze(text)
    return frozenset(words.tokens), frozenset(words.meaning.items())


def similarity(a: Words, b: Words) -> float | None:
    """The overlap when the two texts are similar, else None.

    The count of each number, negation and opposite must be the same in both.
    A count catches a second "not" in a text that already has one.
    """
    score = overlap(a.tokens, b.tokens)
    if score < NEAR or a.meaning != b.meaning:
        return None
    return score


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    score: float


def similar_pairs(words: dict[str, Words]) -> list[Pair]:
    """Every similar pair among {id: Words}. A prefix filter keeps it fast for many facts."""
    freq = Counter(word for w in words.values() for word in w.tokens)
    index: dict[str, list[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    found: list[Pair] = []
    for fid in sorted(words):
        ws = sorted(words[fid].tokens, key=lambda w: (freq[w], w))
        for word in ws[: len(ws) - math.ceil(NEAR * len(ws)) + 1]:
            for other in index[word]:
                pair = (other, fid)
                if pair not in seen:
                    seen.add(pair)
                    score = similarity(words[other], words[fid])
                    if score is not None:
                        found.append(Pair(other, fid, score))
            index[word].append(fid)
    return found
