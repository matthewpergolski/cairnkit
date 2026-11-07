"""Does a `told` claim of an agent match what the owner said? Pure functions, no files.

An agent that writes `memory add --basis told` claims that a person said the text. The claim binds
only when the key words of the text are in the owner's own evidence of this session (see
owner_evidence.py): a prompt the owner typed, the option the owner picked in an agent question, or
the agent proposal that the owner approved with a short "yes".

The data shape. Each piece of evidence is a text with a kind. It splits into sentences, and a
window of one to WINDOW sentences in a row is compared with the claim. A claim matches a window
when the window holds at least THRESHOLD of the claim's key words, and both or neither say "not".
Key words are words with their ending cut, so `commits` and `committing` are one word. Words that
frame a rule (`always`, `must`, `please`, `the`) are no key words. Each word of negation reads as
`not`, so `never` and `do not` are one word, and a "yes" to `do not X` is no match for `X`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The share of the claim's key words that one window of evidence must hold. A claim of up to four
# key words needs all of them, and a longer claim may miss one word in five, for a paraphrase. On
# the cases in tests/test_told_match.py each claim that must match has 0.9 or more, and each that
# must not has 0.75 or less (a claim of four key words that adds one).
THRESHOLD = 0.8
WINDOW = 3
NOT = "not"
NEGATIONS = frozenset({"not", "no", "never", "nor", "without", "avoid", "neither", "none"})
# Words that frame a rule or join a sentence. A rule and the owner's words for it differ in these.
_FRAME_TEXT = (
    "a an the this that these those it its is are was were be been being am do does did done "
    "to of in on at for from by with as into onto about than then so and or if when while "
    "i we you me us my our your they them their he she his her one ones "
    "please should must shall will would can could may might need needs let lets "
    "have has had having use uses used using get gets "
    "always every each all any ever just also only sure ensure make "
    "rule rules remember note save store record memory fact going forward now future time "
    "ok okay yes yeah"
)
FRAME_WORDS = frozenset(_FRAME_TEXT.split())
_WORD = re.compile(r"[^\W_]+")
_CONTRACTIONS = (
    (re.compile(r"(?i)\bcan['\u2019]t\b|\bcannot\b"), "can not"),
    (re.compile(r"(?i)\bwon['\u2019]t\b"), "will not"),
    (re.compile(r"(?i)n['\u2019]t\b"), " not"),
)
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+|\n+")
_DOUBLE_END = re.compile(r"([b-df-hj-np-tv-z])\1$")
# An approval opens the prompt, and the prompt adds no change to it. `yes, but ...` amends the
# proposal, so only the owner's own words count for it.
_APPROVAL = re.compile(
    r"(?i)^\W*(?:yes|yep|yeah|yup|sure|ok|okay|go ahead|go for it|do it|do that|do so|please do"
    r"|sounds good|looks good|lgtm|approved?|agreed?|correct|exactly|perfect|ship it|that works"
    r"|works for me|make it so|y)\b"
)
_AMENDS = re.compile(
    r"(?i)\b(?:but|except|instead|however|although|though|not|no|never|don['\u2019]?t|wait|hold"
    r"|rather|only if|unless)\b|\?"
)
APPROVAL_WORDS = 15
_NEGATIVE_CHOICE = re.compile(r"(?i)^\W*(?:no|nope|never|don['\u2019]?t|do not|skip|cancel)\b")


@dataclass(frozen=True)
class Evidence:
    """One piece of the owner's evidence. `drop` holds key words that must not count from it."""

    kind: str  # "prompt", "choice" or "approval"
    text: str
    drop: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Match:
    kind: str
    coverage: float


def stem(word: str) -> str:
    """One key for the forms of a word. It is a key, so it need not be a real word."""
    if not word.isalpha() or len(word) < 4:
        return word
    if word.endswith("ies"):
        word = word[:-3] + "y"
    elif word.endswith(("sses", "shes", "ches", "xes", "zes")):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    for end in ("ing", "ed"):
        if word.endswith(end) and len(word) - len(end) >= 3:
            word = word[: -len(end)]
            word = word[:-1] if _DOUBLE_END.search(word) and not word.endswith("ll") else word
            break
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def key_words(text: str) -> set[str]:
    """The words of a text that a match compares. Each negation is `not`."""
    for pattern, plain in _CONTRACTIONS:
        text = pattern.sub(plain, text)
    found = set()
    for word in _WORD.findall(text.lower()):
        if word in NEGATIONS:
            found.add(NOT)
        elif word not in FRAME_WORDS:
            found.add(stem(word))
    return found


def _windows(evidence: Evidence) -> list[set[str]]:
    """The key words of each run of up to WINDOW sentences. The owner's question states nothing."""
    parts = [
        key_words(part)
        for part in _SENTENCE_END.split(evidence.text)
        if part.strip() and not (evidence.kind == "prompt" and part.rstrip().endswith("?"))
    ]
    return [
        set().union(*parts[start : start + size])
        for size in range(1, WINDOW + 1)
        for start in range(len(parts) - size + 1)
    ]


def coverage(claim: set[str], evidence: Evidence) -> float:
    """The best share of the claim's key words in one window that agrees on `not`.

    A claim that names an option the owner did not pick matches nothing of that question.
    """
    if not claim or claim & evidence.drop:
        return 0.0
    best = 0.0
    for window in _windows(evidence):
        if (NOT in claim) != (NOT in window):
            continue
        best = max(best, len(claim & window) / len(claim))
    return best


def best_match(text: str, evidence: list[Evidence]) -> Match | None:
    """The evidence that the claim matches best, when it reaches THRESHOLD."""
    claim = key_words(text)
    scored = [Match(item.kind, coverage(claim, item)) for item in evidence]
    best = max(scored, key=lambda match: match.coverage, default=None)
    return best if best and best.coverage >= THRESHOLD else None


def is_approval(prompt: str) -> bool:
    """True for a short prompt that approves what the agent proposed: `yes`, `go ahead`."""
    return (
        bool(_APPROVAL.match(prompt))
        and not _AMENDS.search(prompt)
        and len(prompt.split()) <= APPROVAL_WORDS
    )


def choice_evidence(question: str, options: list[tuple[str, str]], answer: str) -> Evidence | None:
    """What the owner chose in an agent question, from (label, description) options.

    The chosen option counts, and the question too unless the owner said no. A word that only an
    option not chosen holds does not count, so `pytest or unittest?` picked `pytest` gives no
    `unittest`. An answer that is no option is the owner's own words.
    """
    picks = {answer.strip(), *(part.strip() for part in answer.split(","))}
    chosen = [(label, about) for label, about in options if label and label.strip() in picks]
    if not chosen:
        return Evidence("prompt", answer) if answer.strip() else None
    picked = " ".join(f"{label}. {about}" for label, about in chosen)
    others = {word for opt in options if opt not in chosen for word in key_words(" ".join(opt))}
    negative = all(_NEGATIVE_CHOICE.match(label) for label, _ in chosen)
    text = picked if negative else f"{question}\n{picked}"
    return Evidence("choice", text, frozenset(others - key_words(picked)))
