"""When are two facts the same thing said twice?

Two tests:

- `repeat_key`: the same text, byte for byte, apart from whitespace and a final `.`, `,`, `;` or
  `:`. Only this test lets the code end a fact with no agent. A case, a plural, a stop word or a
  symbol can make a different fact: `Foo` and `foo`, `users` and `user`, `-1` and `1`.
- `similarity`: at least 75 percent of the words (Jaccard), with a plural and a stop word ignored.
  This test only flags a pair for an agent, so a false match costs one look and loses nothing.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from cairnkit.state import effective_status

NEAR = 0.75
# Same area and this much overlap: 11 of 13 stale pairs and 0 false pairs on the fixture.
# See docs/forgetting-tests.md. The fixture is hand-written, so this only prompts the agent.
CONFLICT_OVERLAP = 0.25
MAX_COMPARISONS = 200_000

# `!` and `?` stay: `println!` is not `println`, and `is it on?` is not `is it on`.
_FINAL_MARKS = ".,;: "
STOP_WORDS = {"a", "an", "the", "is", "are"}
_WORD = re.compile(r"[^\W_]+")


def repeat_key(text: str) -> str:
    """Two texts are a repeat when this key is the same. A text of marks alone keeps its marks."""
    flat = " ".join(text.split())
    return flat.rstrip(_FINAL_MARKS) or flat


def tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _singular(word: str) -> str:
    """One form for a word and its plural. It is a key, so it need not be a real word."""
    if not word.isalpha():
        return word
    if word.endswith(("ch", "sh", "ss", "x", "z")):  # branch and branches, cache and caches
        return word + "e"
    if len(word) < 4 or word.endswith(("us", "is")) or not word.endswith("s"):
        return word
    return word[:-3] + "y" if word.endswith("ies") else word[:-1]


def analyze(text: str) -> set[str]:
    """The words that `similarity` compares."""
    return {_singular(word) for word in tokens(text) if word not in STOP_WORDS}


def similarity(a: set[str], b: set[str]) -> float | None:
    """The overlap when the two word sets are similar, else None. This only flags a pair."""
    score = overlap(a, b)
    return score if score >= NEAR else None


@dataclass(frozen=True)
class Pair:
    a: str
    b: str
    score: float


def similar_pairs(words: dict[str, set[str]]) -> list[Pair]:
    """Similar pairs among {id: word set}. A prefix filter keeps it fast for many facts.

    Facts that use few distinct words defeat the filter. This runs at session start and it is only
    a clean-up, so at MAX_COMPARISONS it stops and returns what it found. It starts from the newest
    ids, because a new repeat is the one that was not seen in an earlier session.
    """
    freq = Counter(word for w in words.values() for word in w)
    index: dict[str, list[str]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    found: list[Pair] = []
    for fid in sorted(words, reverse=True):
        ws = sorted(words[fid], key=lambda w: (freq[w], w))
        for word in ws[: len(ws) - math.ceil(NEAR * len(ws)) + 1]:
            for other in index[word]:
                pair = (fid, other)
                if pair not in seen:
                    if len(seen) >= MAX_COMPARISONS:
                        return found
                    seen.add(pair)
                    score = similarity(words[fid], words[other])
                    if score is not None:
                        found.append(Pair(fid, other, score))
            index[word].append(fid)
    return found


def possible_conflicts(memory, fact: dict, moment, is_merged) -> list[dict]:
    """Active facts in the same area that share enough words to disagree. It only prompts."""
    area = fact.get("area")
    if not area or area == "general":
        return []
    words = tokens(fact["text"])
    rows = []
    for state in memory.states.values():
        if state["id"] == fact["id"] or state.get("kind") == "rule" or state.get("area") != area:
            continue
        if effective_status(state, moment, is_merged)[0] != "active":
            continue
        score = overlap(words, tokens(str(state.get("text", ""))))
        if score >= CONFLICT_OVERLAP:
            rows.append((score, state))
    rows.sort(key=lambda row: (-row[0], row[1]["id"]))
    return [state for _, state in rows[:3]]
