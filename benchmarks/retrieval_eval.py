"""Measure how well `memory search` finds the right fact for a question.

    uv run python benchmarks/retrieval_eval.py MEMORY_FOLDER PROBES.jsonl [--seed N] [--json]

MEMORY_FOLDER holds `facts/*.jsonl`. PROBES.jsonl has one probe per line:
`{"question": "...", "gold_note_ids": ["f-...", ...]}`. Only active facts are searched.
The time is the clock's now, and a branch merge is not checked, so short-term facts
may score differently on another day.

Each system ranks the facts for each question. The report gives, over all probes:

- any@1: the top result is a gold fact;
- any@5: a gold fact is in the top 5;
- all@5: every gold fact is in the top 5.

Systems: `cairnkit` (the search as it is), `strict` (the search before BM25: every
word must appear), `keyword-count` (the question words found as they are written, no
rarity weight) and `random` (a fixed seed). The last two are the floors.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from cairnkit import ranking
from cairnkit.state import effective_status, fold
from cairnkit.store import fact_files, read_records

TOP = 5
SYSTEMS = ("cairnkit", "strict", "keyword-count", "random")


def read_probes(path: Path) -> list[dict]:
    probes = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            probe = json.loads(line)
            probes.append({"question": probe["question"], "gold": set(probe["gold_note_ids"])})
    return probes


def load_facts(memory_folder: Path) -> list[dict]:
    """The active facts of a memory folder, in id order."""
    records, _ = read_records(fact_files(Path(memory_folder)))
    states = fold(records)
    active = [s for s in states.values() if effective_status(s)[0] == "active"]
    return sorted(active, key=lambda s: s["id"])


def rank_cairnkit(facts: list[dict], question: str, rng: random.Random) -> list[str]:
    return [s["id"] for s, _ in ranking.rank_facts(facts, ranking.query_terms(question))]


def rank_strict(facts: list[dict], question: str, rng: random.Random) -> list[str]:
    return [s["id"] for s, _ in ranking.rank_strict(facts, question)]


def rank_keyword_count(facts: list[dict], question: str, rng: random.Random) -> list[str]:
    """Count the occurrences of the question words in the text, as they are written.

    No filler list, no plural handling, no rarity weight, no length weight.
    """
    terms = set(ranking.WORD.findall(question.lower()))
    scored = []
    for fact in facts:
        found = ranking.WORD.findall(ranking.fact_text(fact).lower())
        count = sum(1 for w in found if w in terms)
        if count:
            scored.append((-count, fact["id"]))
    return [fid for _, fid in sorted(scored)]


def rank_random(facts: list[dict], question: str, rng: random.Random) -> list[str]:
    ids = [s["id"] for s in facts]
    rng.shuffle(ids)
    return ids


RANKERS = {
    "cairnkit": rank_cairnkit,
    "strict": rank_strict,
    "keyword-count": rank_keyword_count,
    "random": rank_random,
}


def evaluate(memory_folder: Path, probes: list[dict], seed: int = 0) -> dict[str, dict[str, float]]:
    facts = load_facts(memory_folder)
    results = {}
    for name in SYSTEMS:
        rng = random.Random(seed)
        any1 = any5 = all5 = 0
        for probe in probes:
            top = RANKERS[name](facts, probe["question"], rng)[:TOP]
            gold = probe["gold"]
            any1 += bool(top[:1] and top[0] in gold)
            any5 += bool(gold & set(top))
            all5 += gold <= set(top)
        total = len(probes) or 1
        results[name] = {
            "any@1": round(any1 / total, 4),
            "any@5": round(any5 / total, 4),
            "all@5": round(all5 / total, 4),
        }
    return results


def table(results: dict[str, dict[str, float]], count: int) -> str:
    lines = [f"{count} probes", f"{'system':<14}{'any@1':>8}{'any@5':>8}{'all@5':>8}"]
    for name, n in results.items():
        lines.append(f"{name:<14}{n['any@1']:>8.2f}{n['any@5']:>8.2f}{n['all@5']:>8.2f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Retrieval eval for `memory search`.")
    parser.add_argument("memory_folder", type=Path)
    parser.add_argument("probes", type=Path)
    parser.add_argument("--seed", type=int, default=0, help="seed of the random baseline")
    parser.add_argument("--json", action="store_true", help="print JSON, not a table")
    args = parser.parse_args(argv)
    probes = read_probes(args.probes)
    results = evaluate(args.memory_folder, probes, args.seed)
    print(json.dumps(results, indent=2) if args.json else table(results, len(probes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
