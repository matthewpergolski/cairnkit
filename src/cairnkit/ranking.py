"""Word ranking for `memory search`: BM25 over the text of facts and of note lines.

Plain Python, no model, no network. A query is split into words. Common filler
words drop out, and a plural loses its ending, so a question finds a note
that states the answer. A note that holds only some of the words still counts.
Rare words count more than common ones.
"""

from __future__ import annotations

import math
import re
from collections import Counter

K1 = 1.2  # how fast a repeated word stops adding score
B = 0.75  # how much a long text is held back

WORD = re.compile(r"[^\W_]+")
FILLER = (
    "a about again all an and any are as at be been but by can could did do does for from "
    "had has have how i if in into is it its my of on or our should so than that the their "
    "then there these they this to was we were what when where which who why will with would "
    "you your"
)
STOPWORDS = frozenset(FILLER.split())


def stem(word: str) -> str:
    """Drop a plural ending: retries to retry, processes to process, emails to email."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("sses"):
        return word[:-2]
    if len(word) > 4 and word.endswith("xes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text: str) -> list[str]:
    """The lower-case, stemmed words of a text, in order, repeats kept."""
    return [stem(w) for w in WORD.findall(text.lower())]


def query_terms(query: str) -> list[str]:
    """The distinct words of a query, in order, without filler words.

    A query of only filler words keeps them, so `memory search the` still works.
    """
    raw = WORD.findall(query.lower())
    kept = [w for w in raw if w not in STOPWORDS] or raw
    return list(dict.fromkeys(stem(w) for w in kept))


def fact_text(state: dict) -> str:
    """The text of a fact that search reads: id, text, area, tags and the reasons of changes."""
    return " ".join(
        [
            state.get("id", ""),
            state.get("text", ""),
            state.get("area", ""),
            " ".join(state.get("tags", [])),
            " ".join(c.get("reason", "") for c in state["history"]),
        ]
    )


def bm25(texts: list[str], terms: list[str]) -> list[float]:
    """The BM25 score of each text for the terms. A text with none of them scores 0."""
    counts = [Counter(words(t)) for t in texts]
    size = len(counts)
    if not size or not terms:
        return [0.0] * size
    lengths = [sum(c.values()) for c in counts]
    average = (sum(lengths) / size) or 1.0
    idf = {}
    for term in terms:
        holders = sum(1 for c in counts if term in c)
        idf[term] = math.log(1 + (size - holders + 0.5) / (holders + 0.5))
    scores = []
    for count, length in zip(counts, lengths, strict=True):
        score = 0.0
        for term in terms:
            tf = count.get(term, 0)
            if tf:
                score += idf[term] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / average))
        scores.append(score)
    return scores


def rank_facts(states: list[dict], terms: list[str]) -> list[tuple[dict, float]]:
    """The facts that hold any term, best first.

    An equal score goes to the newer fact, then to the lower id, so the order never changes
    between runs.
    """
    scores = bm25([fact_text(s) for s in states], terms)
    found = [(s, round(score, 9)) for s, score in zip(states, scores, strict=True) if score > 0]
    found.sort(key=lambda pair: pair[0].get("id", ""))
    found.sort(key=lambda pair: pair[0].get("learned_at", ""), reverse=True)
    found.sort(key=lambda pair: pair[1], reverse=True)
    return found


def rank_strict(states: list[dict], query: str) -> list[tuple[dict, float]]:
    """The old search: every space-separated word must appear as a substring; most hits first."""
    terms = [t for t in query.lower().split() if t]
    found = []
    for state in states:
        hay = fact_text(state).lower()
        if all(term in hay for term in terms):
            found.append((state, float(sum(hay.count(t) for t in terms))))
    found.sort(key=lambda pair: (pair[1], pair[0].get("learned_at", "")), reverse=True)
    return found
