"""Measure which pairs of facts the code would retire with no agent, before and after a rule.

The labelled set is `fixtures/near_repeats.jsonl`. A label says whether the older text can go:
`repeat` when the newer text says everything that the older one says, `different` when it does
not. One author wrote the labels. The `docs` rows are real sentences from this repo. The
`audit-990d229` rows are the false retires that an audit found in the `before` rule.

`before` is the rule that this change replaced, kept here as a copy: the same words in order,
after case, plural, punctuation and stop words. `after` is the rule in the code.

With `--facts FOLDER` it also counts the pairs in each `*.jsonl` of a folder. Give it a copy of a
real memory. It prints only counts and ids, so that private text stays out of a report.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from pathlib import Path

from cairnkit.similar import analyze, repeat_key, similarity
from cairnkit.store import read_records

FIXTURE = Path(__file__).parent / "fixtures" / "near_repeats.jsonl"
_STOP = {"a", "an", "the", "is", "are"}
_NOT_PLURAL = {"https", "news", "windows", "means", "goods", "always", "sometimes", "besides"}


def _singular(word: str) -> str:
    if not word.isalpha() or word in _NOT_PLURAL:
        return word
    if word.endswith(("ch", "sh", "ss", "x", "z")):
        return word + "e"
    if len(word) < 4 or word.endswith(("us", "is")) or not word.endswith("s"):
        return word
    return word[:-3] + "y" if word.endswith("ies") else word[:-1]


def _exact(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[^\W_]+|[+#<>=%$]", text.lower()))


def _near(text: str) -> tuple[str, ...]:
    return tuple(_singular(word) for word in _exact(text) if word not in _STOP)


def before(a: str, b: str) -> bool:
    return bool(_near(a)) and (_exact(a) == _exact(b) or _near(a) == _near(b))


def after(a: str, b: str) -> bool:
    return repeat_key(a) == repeat_key(b)


def score(rule, rows: list[dict]) -> dict[str, int]:
    retired = [row for row in rows if rule(row["a"], row["b"])]
    return {
        "repeats": sum(row["label"] == "repeat" for row in rows),
        "repeats_caught": sum(row["label"] == "repeat" for row in retired),
        "different": sum(row["label"] == "different" for row in rows),
        "false_retires": sum(row["label"] == "different" for row in retired),
        "left_for_the_agent_task": sum(
            not rule(row["a"], row["b"])
            and similarity(analyze(row["a"]), analyze(row["b"])) is not None
            for row in rows
        ),
    }


def facts_in(folder: Path) -> list[dict]:
    records, _ = read_records(sorted(folder.glob("*.jsonl")))
    return [r for r in records if r.get("type") == "fact" and isinstance(r.get("text"), str)]


def count_pairs(folder: Path) -> dict[str, int]:
    facts = facts_in(folder)
    pairs = [
        (a, b)
        for a, b in itertools.combinations(facts, 2)
        if a.get("kind") == b.get("kind") and a.get("scope") == b.get("scope")
    ]
    return {
        "facts": len(facts),
        "before": sum(before(a["text"], b["text"]) for a, b in pairs),
        "after": sum(after(a["text"], b["text"]) for a, b in pairs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--facts", type=Path, action="append", default=[])
    parser.add_argument("--list", action="store_true", help="print each pair that changed verdict")
    args = parser.parse_args()
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    rules = [("before", before), ("after", after)]
    report: dict = {"all": {name: score(rule, rows) for name, rule in rules}}
    for src in sorted({row["src"] for row in rows}):
        part = [row for row in rows if row["src"] == src]
        report[src] = {name: score(rule, part) for name, rule in rules}
    for folder in args.facts:
        report[str(folder)] = count_pairs(folder)
    print(json.dumps(report, indent=1))
    if args.list:
        for row in rows:
            old, new = before(row["a"], row["b"]), after(row["a"], row["b"])
            if old != new:
                print(f"{row['label']:9} before={old!s:5} after={new!s:5} {row['a'][:70]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
