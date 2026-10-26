"""Word ranking for `memory search`: BM25 over the text of facts and of note lines.

Plain Python, no model, no network. A query is split into words. Common filler
words drop out, and a plural loses its ending, so a question finds a note
that states the answer. A note that holds only some of the words still counts.
Rare words count more than common ones. A fact id such as `f-20261026-a053` is one word.
When no whole word matches anywhere, a query word of 4 letters or more may match the
start of a longer word (`deploy` finds `deployment`).
"""

from __future__ import annotations

import math
import re
from collections import Counter

K1 = 1.2  # how fast a repeated word stops adding score
B = 0.75  # how much a long text is held back
PREFIX_MIN = 4  # a query word needs this many letters to match the start of a longer word
SHORT_ENDINGS = frozenset({"", "s", "es", "d", "ed", "er", "ers", "ing"})  # for a 4-letter start

ID = r"f-\d{8}-[0-9a-f]+"
WORD = re.compile(rf"{ID}|[^\W_]+")  # a fact id is one word
FILLER = (
    "a about again all an and any are as at be been but by can could did do does for from "
    "had has have how i if in into is it its my of on or our should so than that the their "
    "then them there these they this to was we were what when where which who why will with "
    "would "
    "you your"
)
STOPWORDS = frozenset(FILLER.split())


ALWAYS_SINGULAR = frozenset({"news", "series", "species"})
IS_PLURALS = ("yses", "ises", "oses", "eses")  # the plural of a word that ends in -is


def stem(word: str) -> str:
    """Drop a plural ending: retries to retry, processes to process, emails to email."""
    if word in ALWAYS_SINGULAR or word.startswith("f-"):
        return word
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("sses"):
        return word[:-2]
    if len(word) > 4 and word.endswith("xes"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def forms(word: str) -> list[str]:
    """The stem of a word, then the other stems that a plural ending could hide.

    `movies` is `movy` by the rule for `-ies`, but its singular is `movie`. `statuses` is
    `statuse` by the rule for `-s`, but its singular is `status`. `alias` loses its `s` to
    the rule for `-s`, so the word itself stays a form: `aliases` also gives `alias`. Both
    sides of a match use every form, so a singular finds its plural and a plural its singular.
    """
    found = [stem(word)]
    if word in ALWAYS_SINGULAR or word.startswith("f-"):
        return found
    if len(word) > 4 and word.endswith("ies"):
        found.append(word[:-1])
    elif (
        len(word) > 4
        and word.endswith(("ses", "ches", "shes", "zes"))
        and not word.endswith("sses")
    ):
        found.append(word[:-2])
        if word.endswith(IS_PLURALS):
            found.append(word[:-2] + "is")  # analyses to analysis
    if word.endswith("s") and not word.endswith("ies") and found[0] != word:
        found.append(word)
    return found


def words(text: str) -> list[str]:
    """The lower-case, stemmed words of a text, in order, repeats kept."""
    return [stem(w) for w in WORD.findall(text.lower())]


def index_words(text: str) -> list[str]:
    """The words of a text for matching: every form of each word, repeats kept."""
    return [form for w in WORD.findall(text.lower()) for form in forms(w)]


def word_counts(text: str) -> tuple[Counter, int]:
    """How many words of a text have each form, and how many words the text has.

    A word with two forms (`movies`) adds to both counts but is one word of the text.
    """
    found = WORD.findall(text.lower())
    return Counter(form for w in found for form in forms(w)), len(found)


def query_terms(query: str) -> list[str]:
    """The distinct words of a query, in order, without filler words.

    A word is one term, as typed. A word that shares a form with an earlier one (`movie`,
    `movies`) is the same term. A query of only filler words keeps them, so
    `memory search the` still works.
    """
    raw = WORD.findall(query.lower())
    kept = [w for w in raw if w not in STOPWORDS] or raw
    terms: list[str] = []
    seen: set[str] = set()
    for word in kept:
        if seen.isdisjoint(forms(word)):
            terms.append(word)
            seen.update(forms(word))
    return terms


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


def prefix_terms(query: str) -> list[str]:
    """The query words, as typed, that are long enough to be searched as the start of a word.

    They are not stemmed: `squas` is the start of `squash`, not the plural of `squa`.
    """
    raw = [w for w in WORD.findall(query.lower()) if not w.startswith("f-")]
    return list(dict.fromkeys(w for w in raw if len(w) >= PREFIX_MIN and w not in STOPWORDS))


def starts(term: str, word: str) -> bool:
    """True when `word` is `term` followed by more letters.

    A term of 5 letters or more may start any longer word (`deploy`, `deployment`). A term
    of 4 letters may only take an ending: `pass` finds `passed`, but `retr` does not find
    `retry` and `port` does not find `portal`.
    """
    if not word.startswith(term):
        return False
    return len(term) >= PREFIX_MIN + 1 or word[len(term) :] in SHORT_ENDINGS


def bm25(texts: list[str], terms: list[str], prefix: bool = False) -> list[float]:
    """The BM25 score of each text for the terms. A text with none of them scores 0.

    With `prefix`, a term also counts at the start of a longer word: `deploy` in `deployment`.
    """
    measured = [word_counts(t) for t in texts]
    counts = [c for c, _ in measured]
    size = len(counts)
    if not size or not terms:
        return [0.0] * size
    lengths = [n for _, n in measured]
    average = (sum(lengths) / size) or 1.0
    idf = {}
    for term in terms:
        holders = sum(1 for c in counts if _tf(c, term, prefix))
        idf[term] = math.log(1 + (size - holders + 0.5) / (holders + 0.5))
    scores = []
    for count, length in zip(counts, lengths, strict=True):
        score = 0.0
        for term in terms:
            tf = _tf(count, term, prefix)
            if tf:
                score += idf[term] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / average))
        scores.append(score)
    return scores


def _tf(count: Counter, term: str, prefix: bool) -> int:
    """How often a term is in a text: as a whole word, or with `prefix` at the start of one.

    A whole word counts as its best form: `movies` in a text that says `movies` twice is 2.
    """
    if not prefix:
        return max((count.get(form, 0) for form in forms(term)), default=0)
    return sum(n for word, n in count.items() if starts(term, word))


def matched(state: dict, terms: list[str], prefix: bool = False) -> set[str]:
    """The query terms that a fact holds."""
    count, _ = word_counts(fact_text(state))
    return {t for t in terms if _tf(count, t, prefix)}


def rank_facts(
    states: list[dict], terms: list[str], prefix: bool = False
) -> list[tuple[dict, float]]:
    """The facts that hold any term, best first. With `prefix`, a term may start a word.

    An equal score goes to the newer fact, then to the lower id, so the order never changes
    between runs.
    """
    scores = bm25([fact_text(s) for s in states], terms, prefix)
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
