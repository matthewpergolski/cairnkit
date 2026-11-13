"""Does a `told` claim of an agent match what the owner said? Pure functions, no files.

An agent that writes `memory add --basis told` claims that a person said the text. The claim binds
only when it is a near-verbatim copy of the owner's own evidence of this session (see
owner_evidence.py): a sentence the owner typed, the label of the option the owner picked in an
agent question, or the agent's closing question that the owner answered with a short "yes".

The data shape. A text splits into units at `.`, `!`, `?`, `;`, `:` and line breaks. A unit is an
ordered list of tokens. A token is a word with its ending cut (`commits` and `committing` are one
token), or a literal kept whole and exact: a number, a path, a flag, a name with a dot, a slash, an
underscore or a capital inside it. Each negation (`not`, `no`, `never`, `don't`) is the token
`not`. Frame words go: articles, `please`, pronouns, punctuation and case. A rule frame at the
start or the end of a unit goes too (`from now on`, `always`, `remember to`, `as a rule`).

The match. The claim's units split into runs of units in a row, and each run must match one unit
of one piece of evidence, so that no claim joins words from two of the owner's sentences into one
statement. In the claim, an ellipsis (`\u2026`, or `...` beside a space) also ends a unit: it marks
the words that a quote leaves out, so each part on its side must be a copy too. A run can join the
parts again, so a quote of one sentence with a gap still matches under the rules below. A run
matches a unit when:

- each token of the run is in the unit, in the same order (so `dev, never main` is not
  `main, never dev`);
- the unit's tokens that the run leaves out are no polarity or scope word and no literal, so
  `until CI is green`, `except main and dev`, `stop` and `yet` cannot be dropped;
- the run holds at least PRECISION of the unit's tokens, so a qualifier cannot be dropped.

A unit of a typed prompt that asks (it ends in `?`, or it opens with `can you`, `what`, ...) or
that opens with `if` states no rule, and no claim matches it. One exception: a claim with a rule
and a question binds when it is the owner's whole prompt, with only case, spaces and the marks at
its end changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache

# The share of the owner's unit that a run of the claim must hold. One word in five may go, for
# a word such as `so` or `then`; a polarity word, a scope word or a literal may never go.
PRECISION = 0.8
NOT = "not"
NEGATIONS = frozenset({"not", "no", "never", "nor", "neither", "none"})
# Words that turn or limit a rule. They must be the same in the claim and the owner's unit.
_STRICT_TEXT = (
    "not stop skip quit refuse disallow forbid avoid except unless until without "
    "only all always every any must may can before after yet if"
)
_FRAME_TEXT = (
    "a an the please i we you me us my our your yours it its they them their he she him his her "
    "this that these those"
)
FRAME_WORDS = frozenset(_FRAME_TEXT.split())
_TOKEN = re.compile(r"(?<![\w.])\.\w[\w./-]*|(?<![\w-])--?\w[\w-]*|\w[\w./@+-]*")
_CONTRACTIONS = (
    (re.compile(r"(?i)\b(?:do|does|did)\s+not\b|\b(?:don|doesn|didn)['\u2019]t\b"), "not"),
    (re.compile(r"(?i)\bcan['\u2019]t\b|\bcannot\b"), "can not"),
    (re.compile(r"(?i)\bwon['\u2019]t\b"), "will not"),
    (re.compile(r"(?i)n['\u2019]t\b"), " not"),
)
_UNIT_END = re.compile(r"(?<=[.!?;:])\s+|\n+")
# Only in a claim. `main...dev` is a range of commits, not a gap in a quote.
_GAP = re.compile(r"\s*\u2026\s*|\s+\.{3}\s*|\.{3}(?:\s+|$)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
_DOUBLE_END = re.compile(r"([b-df-hj-np-tv-z])\1$")
_RULE_FRAME = (
    r"from now on|going forward|in (?:the )?future|for the future|as a rule|"
    r"remember(?: to| that)?|keep in mind(?: that)?|note(?: that)?|"
    r"make sure(?: to| that| you)?|be sure to|please|always"
)
_LEAD = re.compile(rf"(?i)^(?:[\W_]*(?:{_RULE_FRAME})\b)+[\W_]*")
# Who said it and when, ahead of the owner's words in a claim: `The owner said:`, `User
# decided 2026-11-08:`. Only a name, one word in brackets, a verb and a date: no room for a rule.
_ATTRIBUTION = re.compile(
    r"(?i)(?:on\s+\d{4}-\d{2}-\d{2},?\s+)?(?:the\s+)?(?P<who>[A-Za-z][\w.'-]*)"
    r"(?:\s*\([A-Za-z][\w.'-]*\))?(?P<verb>\s+(?:said|says|decided|wrote|stated|confirmed"
    r"|approved|asked|replied|answered|told(?:\s+(?:me|us))?))?"
    r"(?:\s+(?:on\s+)?\d{4}-\d{2}-\d{2})?\s*:"
)
_PERSON = frozenset({"owner", "user"})
_TRAIL = re.compile(r"(?i)(?:[\s,]*\b(?:from now on|going forward|as a rule|please))+[\W_]*$")
# How an agent asks to save a rule, before the rule itself: `Shall I add a rule that ...`.
_ASK = re.compile(
    r"(?i)^\W*(?:shall|should|can|may) i|^\W*(?:do you want|would you like|want) me to"
    r"|^\W*(?:ok|okay) to"
)
_ASK_REST = re.compile(
    r"(?i)^\s*(?:go ahead and\s+)?(?:(?:save|store|add|record|keep|write|remember|make)\b"
    r"(?:\s+(?:it|this|that|a|the|this|one))?(?:\s+(?:rule|note|memory|fact))?"
    r"(?:\s+as a rule)?(?:\s+(?:that|saying|to say))?)?[\s,:]*"
)
_QUESTION = re.compile(
    r"(?i)^(?:(?:can|could|would|will|should|shall|do|does|did|is|are|was|were|may|might|have"
    r"|has|had|am)\s+(?:you|we|i|it|they|this|that|there|someone|anyone|he|she)\b"
    r"|(?:what|why|how|where|which|who|whom|whose)\b)"
)
# A hypothetical states no rule. A plain condition does: "If you touch the schema, update
# FORMAT.md" is a rule, and `if` is a strict word, so a claim that drops the condition fails.
_CONDITION = re.compile(r"(?i)^(?:what if|suppose|imagine)\b")
APPROVALS = frozenset(
    {"yes", "y", "yep", "go ahead", "do it", "do that", "approved", "sounds good", "ok do it"}
)
# A claim of only these words tells a later reader nothing, so it confirms nothing. The list is
# wider than APPROVALS: a word here that is no yes costs one refused empty claim, but a word in
# APPROVALS makes the closing question of the agent bind. `go with your rec` is no approval: the
# closing question is often not the recommendation.
SAYS_NOTHING = APPROVALS | {
    "ok", "okay", "k", "sure", "yeah", "yup", "lgtm", "ship it", "go for it", "please do",
    "do", "proceed", "agreed", "correct", "right", "fine", "great", "perfect", "cool", "done",
    "thanks", "thank you", "ty", "go with your rec", "go with your recommendation",
}  # fmt: skip


def _run_of(phrases: frozenset[str], lead: str) -> re.Pattern[str]:
    """One or more phrases in a row, each with `lead` or not: `yes, go ahead`, `let's do it`."""
    choices = "|".join(re.escape(phrase) for phrase in sorted(phrases, key=len, reverse=True))
    part = rf"(?:{lead})?(?:{choices})(?: please)?"
    return re.compile(rf"(?:please )?{part}(?: {part})*")


# `I'll do it` is the owner who takes the task, so it approves no question.
_APPROVAL_RUN = _run_of(APPROVALS, r"let s |lets ")
_NOTHING_RUN = _run_of(SAYS_NOTHING, r"i ll |i will |let s |lets ")
# A word that is no a-z word: a digit or a letter of another script. `yes 2` picks something.
_OTHER_WORD = re.compile(r"[^\Wa-zA-Z]")
# Past the a-z words and the marks of a sentence, a claim with anything else (`#42`, `0018`) says
# which work the yes is for.
_OTHER_MARK = re.compile(r"[^a-zA-Z\s.,!?;:'\"()\u2018\u2019\u201c\u201d\u2013\u2014-]")


def _letters(text: str) -> str:
    return " ".join(re.findall(r"[a-z]+", text.lower()))


@dataclass(frozen=True)
class Evidence:
    """One piece of the owner's evidence."""

    kind: str  # "prompt", "choice" or "approval"
    text: str


@dataclass(frozen=True)
class Match:
    kind: str


def stem(word: str) -> str:
    """One key for the forms of a word. It is a key, so it need not be a real word.

    No word but a negation gives `not`: `noted` is `noted`.
    """
    if len(word) < 4 or not word.isalpha():
        return word
    base = word
    if base.endswith("ies"):
        base = base[:-3] + "y"
    elif base.endswith(("sses", "shes", "ches", "xes", "zes")):
        base = base[:-2]
    elif base.endswith("s") and not base.endswith(("ss", "us", "is")):
        base = base[:-1]
    for end in ("ing", "ed"):
        if base.endswith(end) and len(base) - len(end) >= 3:
            base = base[: -len(end)]
            base = base[:-1] if _DOUBLE_END.search(base) and not base.endswith("ll") else base
            break
    base = base[:-1] if base.endswith("e") and len(base) > 3 else base
    return word if base == NOT else base


STRICT = frozenset(stem(word) for word in _STRICT_TEXT.split())


def _literal(raw: str) -> bool:
    """A number, a path, a flag or a name: kept whole, never cut, never left out."""
    return bool(re.search(r"[\d/._@+]", raw)) or raw[0] in "-." or raw[1:] != raw[1:].lower()


Token = tuple[str, bool]  # (the key, True for a token that may never be left out)


def tokens(unit: str) -> tuple[Token, ...]:
    """The tokens of one unit, in order. See the module text."""
    for pattern, plain in _CONTRACTIONS:
        unit = pattern.sub(plain, unit)
    found: list[Token] = []
    for raw in _TOKEN.findall(unit):
        raw = raw.rstrip(".-/")
        if not raw:
            continue
        if _literal(raw):
            found.append((raw.lower(), True))
            continue
        for part in raw.lower().split("-"):
            key = NOT if part in NEGATIONS else stem(part)
            if part and part not in FRAME_WORDS:
                found.append((key, key in STRICT))
    return tuple(found)


def _unframed(unit: str) -> str:
    return _TRAIL.sub("", _LEAD.sub("", unit.strip()))


def _states_a_rule(unit: str) -> bool:
    text = unit.strip()
    return not (text.endswith("?") or _QUESTION.match(text) or _CONDITION.match(text))


def _asked(unit: str) -> str:
    """The rule in a unit of the agent's question, with the asking words gone."""
    text = unit.strip().rstrip("?")
    asking = _ASK.match(text)
    return _ASK_REST.sub("", text[asking.end() :], count=1) if asking else text


def units(evidence: Evidence) -> list[tuple[Token, ...]]:
    """The units of the evidence that state something, as tokens."""
    found = []
    for part in _UNIT_END.split(evidence.text):
        if evidence.kind == "approval":
            part = _asked(part)
        elif evidence.kind == "prompt" and not _states_a_rule(_unframed(part)):
            continue
        words = tokens(_unframed(part))
        if words:
            found.append(words)
    return found


def _is_attribution(unit: str) -> bool:
    """`The owner said:` or `User:`, never `Never:` or `Optional:`. A verb or a person word
    must name who spoke, and no word that turns or limits the rule may stand in it."""
    found = _ATTRIBUTION.fullmatch(unit)
    if not found or not (found["verb"] or found["who"].lower() in _PERSON):
        return False
    return not any(token in STRICT or token == NOT for token, _ in tokens(unit.rstrip(":")))


def _claim_parts(text: str) -> list[str]:
    # An ellipsis marks words left out of ONE sentence of the owner: the parts must match that
    # sentence in order, so the gap is only a space here. Joining two sentences of the owner
    # could turn "No. Commit to main." into "Never commit to main".
    parts = _UNIT_END.split(_GAP.sub(" ", text))
    if parts and _is_attribution(parts[0].strip()):
        parts = parts[1:]  # who said it and when, not part of the rule
    return [_unframed(part) for part in parts if tokens(_unframed(part))]


def _plain(text: str) -> str:
    """Text with only case, spaces and the marks at its end made the same."""
    return re.sub(r"\s+", " ", text).strip().rstrip(".!?;:, ").lower()


def _whole_prompt(text: str, evidence: list[Evidence]) -> Match | None:
    """The prompt that the claim copies whole, word for word, or None."""
    head, *rest = _UNIT_END.split(text.strip(), maxsplit=1)
    words = _plain(rest[0] if rest and _is_attribution(head.strip()) else text)
    found = any(item.kind == "prompt" and _plain(item.text) == words for item in evidence)
    return Match("prompt") if words and found else None


def run_matches(run: tuple[Token, ...], unit: tuple[Token, ...]) -> bool:
    """True when a run of the claim is a near-verbatim copy of one unit. See the module text."""
    if not run or len(run) < PRECISION * len(unit):
        return False

    @cache
    def fits(i: int, j: int) -> bool:
        if i == len(run):
            return not any(keep for _, keep in unit[j:])
        if len(unit) - j < len(run) - i:
            return False
        if unit[j][0] == run[i][0] and fits(i + 1, j + 1):
            return True
        return not unit[j][1] and fits(i, j + 1)

    return fits(0, 0)


def _matches(claim: list[tuple[Token, ...]], owner: list[tuple[Token, ...]]) -> bool:
    """True when the claim's units split into runs in a row that each match one owner unit."""
    done = [True] + [False] * len(claim)
    for end in range(1, len(claim) + 1):
        done[end] = any(
            done[start] and any(run_matches(sum(claim[start:end], ()), unit) for unit in owner)
            for start in range(end)
        )
    return bool(claim) and done[-1]


def best_match(text: str, evidence: list[Evidence]) -> Match | None:
    """The first piece of evidence that the claim copies, or None.

    A question states no rule, so a question in a claim matches no unit of the owner. A claim
    with a rule and a question binds when it is the owner's whole prompt, such as "ok let's make
    these optimizations. how?": the same words in the same order. Only case, spaces and the marks
    at the end can differ, so no question of the owner can move to a rule of another sentence.
    The question stays in the fact, so a reader sees it.

    The asking words go from an approved question (see `units`), so they may go from the claim
    too: the claim can copy the whole question, such as "Shall I end f-20261113-0a1b (Use uv)?".
    """
    parts = _claim_parts(text)
    rules = [_states_a_rule(part) for part in parts]
    if any(rules) and not all(rules) and (whole := _whole_prompt(text, evidence)):
        return whole
    claim = [tokens(part) for part in parts]
    asked = [tokens(_asked(part)) for part in parts]
    for item in evidence:
        owner = units(item)
        if _matches(claim, owner) or (item.kind == "approval" and _matches(asked, owner)):
            return Match(item.kind)
    return None


def is_approval(prompt: str) -> bool:
    """True for a prompt that is only a short yes: `yes`, `go ahead`, `ok, do it`.

    `ok thanks`, `correct`, `I'll do it`, `yes 2` and `yes, and also ...` approve no rule.
    """
    return not _OTHER_WORD.search(prompt) and bool(_APPROVAL_RUN.fullmatch(_letters(prompt)))


def only_approval(text: str) -> bool:
    """True for a claim whose words say nothing, with `The owner said:` or not: `yes`, `ok`.

    It tells a later reader nothing. The words of the proposal that the yes approved do.
    """
    parts = [part for part in _UNIT_END.split(_GAP.sub(" ", text)) if part.strip()]
    if parts and _is_attribution(parts[0].strip()):
        parts = parts[1:]
    rest = " ".join(_unframed(part) for part in parts)
    return not _OTHER_MARK.search(rest) and bool(_NOTHING_RUN.fullmatch(_letters(rest)))


def final_question(message: str) -> str | None:
    """The sentence that ends the agent's message, when it is a question, or None.

    A short "yes" answers that question, and nothing else of the message.
    """
    sentences = [part for part in _SENTENCE_END.split(message.strip()) if part.strip()]
    last = sentences[-1].strip() if sentences else ""
    return last if last.endswith("?") else None


def choice_evidence(labels: list[str], answer: str) -> Evidence | None:
    """What the owner chose in an agent question: the labels of the chosen options.

    The question and the descriptions of the options are the agent's words, so they do not
    count. An answer that is no option is the owner's own words.
    """
    picks = {answer.strip(), *(part.strip() for part in answer.split(","))}
    chosen = [label.strip() for label in labels if label.strip() and label.strip() in picks]
    if not chosen:
        return Evidence("prompt", answer) if answer.strip() else None
    return Evidence("choice", "\n".join(chosen))
