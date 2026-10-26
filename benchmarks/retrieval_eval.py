"""Measure how well `memory search` and `memory load` find the right fact.

    uv run python benchmarks/retrieval_eval.py MEMORY_FOLDER PROBES.jsonl
        [--seed N] [--budget N ...] [--no-load] [--json]

MEMORY_FOLDER holds `facts/*.jsonl`. PROBES.jsonl has one probe per line:

    {"question": "...", "gold_note_ids": ["f-..."], "stale_note_ids": [...],
     "decoy_note_ids": [...], "kind": "fix"}

Only `question` and `gold_note_ids` are required. A stale fact is an older, wrong answer
that a newer gold fact replaces. A decoy shares words with a gold fact but is not the answer.

The time is fixed (NOW, below) and the writer is pinned, so a run does not depend on the
real clock. A branch merge is not checked. The harness uses only the standard library and
cairnkit, and it never writes to the memory folder.

Search. Each system ranks the facts for each question. Numbers over all probes:

- any@1: the top result is a gold fact;
- any@5: a gold fact is in the top 5;
- all@5: every gold fact is in the top 5;
- stale>gold: a stale fact ranks above the best gold fact (probes with stale facts only);
- stale@5: a stale fact is in the top 5 (probes with stale facts only);
- decoy@1: the top result is a decoy (probes with decoys only);
- empty: the number of probes that got no result at all;
- n-stale: how many probes the two stale rates are measured on. A superseded fact is not in
  a search over active facts, so it cannot rank and its probe is left out.

Systems: `cairnkit` (the search as it is, with the part-of-word fallback),
`cairnkit-whole-word` (the same without the fallback), `strict` (the search before BM25),
`keyword-count` and `random` (a fixed seed; the floors). Controls prove that the harness
can tell good from bad: `oracle` (gold first) must score 1.0, and `inverted` (worst score
first) and `mismatched-query` (the next probe's question) must score near random or below.

Load. `memory load` does not read the question. It fills a word budget from the same facts
for every probe, so the loaded set is one set per budget. For each probe the report says
whether a gold fact is in it (gold@load), whether all are (gold-all@load), and how many
stale or decoy facts are in it. A superseded fact is never loaded. Only a stale fact that
nobody marked as superseded can leak. Floors: `newest-first` and `random-fill` (the mean
of 20 seeds), both with the same budget.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import re
import sys
import tempfile
from pathlib import Path

from cairnkit import ranking
from cairnkit.clock import parse_time
from cairnkit.load import active_states, build_output
from cairnkit.memory import Memory
from cairnkit.paths import Project
from cairnkit.selection import render, words_in
from cairnkit.state import effective_status, fold
from cairnkit.store import fact_files, read_records

NOW = "2026-10-20T12:00:00+00:00"
TOP = 5
MIN_GROUP = 10  # a group of fewer probes is flagged as unreliable
BOOTSTRAP = 2000
SYSTEMS = ("cairnkit", "cairnkit-whole-word", "strict", "keyword-count", "random")
CONTROLS = ("oracle", "inverted", "mismatched-query")
LOAD_SYSTEMS = ("cairnkit", "newest-first", "random-fill")
RANDOM_SEEDS = 20
ID_IN_LINE = re.compile(r"^- \[(f-\d{8}-[0-9a-f]{4})\]")


def read_probes(path: Path) -> list[dict]:
    probes = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            probe = json.loads(line)
            probes.append(
                {
                    "question": probe["question"],
                    "gold": set(probe["gold_note_ids"]),
                    "stale": set(probe.get("stale_note_ids", ())),
                    "decoy": set(probe.get("decoy_note_ids", ())),
                    "kind": probe.get("kind", "general"),
                }
            )
    return probes


def _states(memory_folder: Path) -> list[dict]:
    records, _ = read_records(fact_files(Path(memory_folder)))
    return [s for s in fold(records).values() if s.get("status") != "purged"]


def load_facts(memory_folder: Path, include_ended: bool = False, now: str = NOW) -> list[dict]:
    """The facts a search reads, in id order: the active ones, or all with `include_ended`."""
    moment = parse_time(now)
    states = _states(memory_folder)
    if not include_ended:
        states = [s for s in states if effective_status(s, moment)[0] == "active"]
    return sorted(states, key=lambda s: s["id"])


def check_probes(memory_folder: Path, facts: list[dict], probes: list[dict]) -> None:
    """Fail when a probe names a fact that is not there. A silent drop would flatter a system."""
    known = {s["id"] for s in _states(memory_folder)}
    searched = {s["id"] for s in facts}
    for number, probe in enumerate(probes, start=1):
        for name in ("gold", "stale", "decoy"):
            for fid in probe[name] - known:
                raise ValueError(f"probe {number} names {name} fact {fid}, which does not exist")
        for fid in probe["gold"] - searched:
            raise ValueError(f"probe {number} has gold fact {fid}, which this corpus does not hold")


# --- search systems ---------------------------------------------------------------------


def rank_cairnkit(facts: list[dict], question: str, rng: random.Random) -> list[str]:
    terms = ranking.query_terms(question)
    ranked = ranking.rank_facts(facts, terms)
    if not ranked and ranking.prefix_terms(question):
        ranked = ranking.rank_facts(facts, ranking.prefix_terms(question), prefix=True)
    return [s["id"] for s, _ in ranked]


def rank_whole_word(facts: list[dict], question: str, rng: random.Random) -> list[str]:
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


def rank_inverted(facts: list[dict], question: str, rng: random.Random) -> list[str]:
    """Control: every fact, the lowest cairnkit score first."""
    scores = ranking.bm25([ranking.fact_text(s) for s in facts], ranking.query_terms(question))
    return [
        s["id"]
        for _, s in sorted(zip(scores, facts, strict=True), key=lambda p: (p[0], p[1]["id"]))
    ]


RANKERS = {
    "cairnkit": rank_cairnkit,
    "cairnkit-whole-word": rank_whole_word,
    "strict": rank_strict,
    "keyword-count": rank_keyword_count,
    "random": rank_random,
    "inverted": rank_inverted,
}


def score_ranking(order: list[str], probe: dict, corpus: set[str]) -> dict:
    """What one ranked list says about one probe.

    A stale or decoy fact that the corpus does not hold (a superseded fact, in a search over
    active facts) cannot rank, so it does not count: the probe is left out of that rate.
    """
    gold = probe["gold"]
    stale = probe["stale"] & corpus
    decoy = probe["decoy"] & corpus
    top = order[:TOP]
    place = {fid: i for i, fid in enumerate(order)}
    far = len(order) + 1
    best_gold = min((place.get(g, far) for g in gold), default=far)
    best_stale = min((place.get(s, far) for s in stale), default=far)
    return {
        "any1": bool(top[:1] and top[0] in gold),
        "any5": bool(gold & set(top)),
        "all5": gold <= set(top),
        "stale>gold": (best_stale < best_gold) if stale else None,
        "stale@5": bool(stale & set(top)) if stale else None,
        "decoy@1": bool(top[:1] and top[0] in decoy) if decoy else None,
        "empty": not order,
    }


def search_outcomes(facts: list[dict], probes: list[dict], seed: int = 0) -> dict[str, list[dict]]:
    """For every system and control, one outcome per probe.

    `random-mean` is the random order averaged over RANDOM_SEEDS seeds, a steadier floor than
    the one seed of `random`.
    """
    corpus = {s["id"] for s in facts}
    out: dict[str, list[dict]] = {}
    for name in (*SYSTEMS, *CONTROLS):
        rng = random.Random(seed)
        rows = []
        for i, probe in enumerate(probes):
            if name == "oracle":
                rest = [s["id"] for s in facts if s["id"] not in probe["gold"]]
                order = sorted(probe["gold"]) + rest
            elif name == "mismatched-query":
                other = probes[(i + 1) % len(probes)]["question"]
                order = rank_cairnkit(facts, other, rng)
            else:
                order = RANKERS[name](facts, probe["question"], rng)
            rows.append(score_ranking(order, probe, corpus))
        out[name] = rows
    out["random-mean"] = [
        _mean_rows(
            [
                score_ranking(
                    rank_random(facts, probe["question"], random.Random(k)), probe, corpus
                )
                for k in range(RANDOM_SEEDS)
            ]
        )
        for probe in probes
    ]
    return {name: out[name] for name in (*SYSTEMS[:-1], "random", "random-mean", *CONTROLS)}


def _mean_rows(rows: list[dict]) -> dict:
    """The mean of the outcomes of one probe over several runs (None stays None)."""
    return {
        key: (None if rows[0][key] is None else sum(r[key] for r in rows) / len(rows))
        for key in rows[0]
    }


def summarize(rows: list[dict]) -> dict[str, float | int | None]:
    """The rates of one system over some probes. A rate with no probe to measure is None."""

    def rate(name: str) -> float | None:
        flags = [r[name] for r in rows if r[name] is not None]
        return round(sum(flags) / len(flags), 4) if flags else None

    return {
        "any@1": rate("any1"),
        "any@5": rate("any5"),
        "all@5": rate("all5"),
        "stale>gold": rate("stale>gold"),
        "stale@5": rate("stale@5"),
        "decoy@1": rate("decoy@1"),
        "empty": round(sum(r["empty"] for r in rows), 4),
        "n-stale": sum(r["stale>gold"] is not None for r in rows),
    }


def evaluate(
    memory_folder: Path, probes: list[dict], seed: int = 0, include_ended: bool = False
) -> dict[str, dict]:
    facts = load_facts(memory_folder, include_ended)
    check_probes(memory_folder, facts, probes)
    return {name: summarize(rows) for name, rows in search_outcomes(facts, probes, seed).items()}


# --- splits and paired comparison -------------------------------------------------------


def overlap(probe: dict, facts_by_id: dict[str, dict]) -> int:
    """The most question words (as search sees them) that one gold fact shares with the question."""
    terms = ranking.query_terms(probe["question"])
    return max(
        (
            sum(1 for t in terms if set(ranking.forms(t)) & set(ranking.index_words(text)))
            for text in (facts_by_id[g]["text"] for g in probe["gold"])
        ),
        default=0,
    )


def split(
    memory_folder: Path, probes: list[dict], key, seed: int = 0, include_ended: bool = False
) -> dict[str, dict]:
    """Search numbers per group of probes. `key(probe, facts_by_id)` names the group."""
    facts = load_facts(memory_folder, include_ended)
    by_id = {s["id"]: s for s in facts}
    outcomes = search_outcomes(facts, probes, seed)
    groups: dict[str, list[int]] = {}
    for i, probe in enumerate(probes):
        groups.setdefault(key(probe, by_id), []).append(i)
    return {
        group: {
            "n": len(idx),
            "unreliable": len(idx) < MIN_GROUP,
            **{name: summarize([rows[i] for i in idx]) for name, rows in outcomes.items()},
        }
        for group, idx in sorted(groups.items())
    }


def split_by_kind(memory_folder: Path, probes: list[dict], **kwargs) -> dict[str, dict]:
    return split(memory_folder, probes, lambda p, _: p["kind"], **kwargs)


def split_by_overlap(memory_folder: Path, probes: list[dict], **kwargs) -> dict[str, dict]:
    def bucket(probe: dict, by_id: dict[str, dict]) -> str:
        return "0-1 shared words" if overlap(probe, by_id) <= 1 else "2+ shared words"

    return split(memory_folder, probes, bucket, **kwargs)


def bootstrap_delta(
    a: list[float], b: list[float], iters: int = BOOTSTRAP, seed: int = 0
) -> tuple[float, float, float]:
    """Mean of a minus mean of b over paired probes, with a 95% bootstrap interval.

    The probes are resampled with replacement, as pairs, so a probe that both systems get
    right or wrong cancels out.
    """
    n = len(a)
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    delta = sum(diffs) / n
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(iters))
    return delta, means[int(0.025 * iters)], means[int(0.975 * iters) - 1]


def compare(outcomes: dict[str, list[dict]], a: str, b: str, metric: str) -> dict:
    """System a against system b on one 0/1 metric: delta, 95% CI, and the probes that differ."""
    xs = [float(r[metric]) for r in outcomes[a]]
    ys = [float(r[metric]) for r in outcomes[b]]
    delta, low, high = bootstrap_delta(xs, ys)
    return {
        "a": a,
        "b": b,
        "metric": metric,
        "n": len(xs),
        "delta": round(delta, 4),
        "ci95": [round(low, 4), round(high, 4)],
        "a-only": sum(1 for x, y in zip(xs, ys, strict=True) if x > y),
        "b-only": sum(1 for x, y in zip(xs, ys, strict=True) if y > x),
    }


# --- load -------------------------------------------------------------------------------


@contextlib.contextmanager
def pinned_environment(now: str):
    """The fixed time for the load code, and no writer or branch from the caller."""
    saved = {k: os.environ.get(k) for k in ("MEMORY_NOW", "MEMORY_WRITER")}
    os.environ["MEMORY_NOW"] = now
    os.environ.pop("MEMORY_WRITER", None)
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def loaded_ids(memory: Memory, budget: int) -> list[str]:
    """The ids that `memory load --budget N` shows, read from its output."""
    ids = []
    for line in build_output(memory, None, budget):
        found = ID_IN_LINE.match(line)
        if found:
            ids.append(found.group(1))
    return ids


def fill(states: list[dict], budget: int) -> list[str]:
    """Take facts in the given order while they fit the word budget. 0 means no limit."""
    chosen, used = [], 0
    for state in states:
        cost = words_in(render(state))
        if budget and used + cost > budget:
            continue
        chosen.append(state["id"])
        used += cost
    return chosen


def load_row(shown: set[str], probes: list[dict], corpus: set[str]) -> dict:
    gold_any = [bool(p["gold"] & shown) for p in probes]
    gold_all = [p["gold"] <= shown for p in probes]
    probes_stale = [{**p, "stale": p["stale"] & corpus} for p in probes]
    probes_decoy = [{**p, "decoy": p["decoy"] & corpus} for p in probes]
    with_stale = [p for p in probes_stale if p["stale"]]
    with_decoy = [p for p in probes_decoy if p["decoy"]]
    return {
        "gold@load": sum(gold_any) / len(probes),
        "gold-all@load": sum(gold_all) / len(probes),
        "stale-leak": (sum(bool(p["stale"] & shown) for p in with_stale) / len(with_stale))
        if with_stale
        else None,
        "stale-loaded": (sum(len(p["stale"] & shown) for p in with_stale) / len(with_stale))
        if with_stale
        else None,
        "decoy-loaded": (sum(len(p["decoy"] & shown) for p in with_decoy) / len(with_decoy))
        if with_decoy
        else None,
        "facts": len(shown),
        "n-stale": len(with_stale),
    }


def evaluate_load(
    memory_folder: Path, probes: list[dict], budget: int, now: str = NOW
) -> dict[str, dict]:
    """Score `memory load --budget N`, and two floors with the same budget."""
    corpus = {s["id"] for s in load_facts(memory_folder, now=now)}
    check_probes(memory_folder, load_facts(memory_folder, now=now), probes)
    with pinned_environment(now), tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)  # an empty folder outside any repo: no branch, no git
        memory = Memory.open(Project(root=root, main_root=root), str(memory_folder))
        shown = loaded_ids(memory, budget)
        rules = [s for s in active_states(memory) if s.get("kind") == "rule"]
        rest = [s for s in active_states(memory) if s.get("kind") != "rule"]
        always = [s["id"] for s in rules]
        newest = sorted(rest, key=lambda s: s["id"])
        newest.sort(key=lambda s: s.get("learned_at", ""), reverse=True)
        rows = {
            "cairnkit": load_row(set(shown), probes, corpus),
            "newest-first": load_row(set(always + fill(newest, budget)), probes, corpus),
        }
    floors = []
    for seed in range(RANDOM_SEEDS):
        shuffled = list(rest)
        random.Random(seed).shuffle(shuffled)
        floors.append(load_row(set(always + fill(shuffled, budget)), probes, corpus))
    rows["random-fill"] = {
        key: (
            None if floors[0][key] is None else round(sum(f[key] for f in floors) / len(floors), 4)
        )
        for key in floors[0]
    }
    for row in rows.values():
        for key, value in row.items():
            if isinstance(value, float):
                row[key] = round(value, 4)
    return rows


# --- report -----------------------------------------------------------------------------


def report(
    memory_folder: Path, probes: list[dict], seed: int, budgets: list[int], with_load: bool = True
) -> dict:
    facts = load_facts(memory_folder)
    ended = load_facts(memory_folder, include_ended=True)
    check_probes(memory_folder, facts, probes)
    outcomes = search_outcomes(facts, probes, seed)
    result: dict = {
        "now": NOW,
        "seed": seed,
        "probes": len(probes),
        "facts": len(facts),
        "facts-incl-ended": len(ended),
        "search": {name: summarize(rows) for name, rows in outcomes.items()},
        "search-incl-ended": evaluate(memory_folder, probes, seed, include_ended=True),
        "by-kind": split_by_kind(memory_folder, probes, seed=seed),
        "by-overlap": split_by_overlap(memory_folder, probes, seed=seed),
        "paired": [
            compare(outcomes, "cairnkit", "keyword-count", "any1"),
            compare(outcomes, "cairnkit", "keyword-count", "any5"),
            compare(outcomes, "cairnkit", "cairnkit-whole-word", "any1"),
            compare(outcomes, "cairnkit", "cairnkit-whole-word", "any5"),
            compare(outcomes, "cairnkit", "strict", "any5"),
        ],
    }
    if with_load:
        result["load"] = {str(b): evaluate_load(memory_folder, probes, b) for b in budgets}
    return result


def _cell(value) -> str:
    return "-" if value is None else (f"{value:.2f}" if isinstance(value, float) else str(value))


def _grid(rows: dict[str, dict], columns: list[str], first: str = "system") -> list[str]:
    lines = [f"{first:<20}" + "".join(f"{c:>14}" for c in columns)]
    for name, numbers in rows.items():
        lines.append(f"{name:<20}" + "".join(f"{_cell(numbers.get(c)):>14}" for c in columns))
    return lines


def table(result: dict) -> str:
    cols = ["any@1", "any@5", "all@5", "stale>gold", "stale@5", "decoy@1", "empty", "n-stale"]
    lines = [
        f"{result['probes']} probes, {result['facts']} active facts "
        f"({result['facts-incl-ended']} with ended ones), time {result['now']}, "
        f"random seed {result['seed']}",
        "",
        "Search over active facts",
        *_grid(result["search"], cols),
    ]
    if result["facts-incl-ended"] != result["facts"]:
        lines += ["", "Search over all facts, as `memory search --all`"]
        lines += _grid(result["search-incl-ended"], cols)
    for title, groups in (("kind", result["by-kind"]), ("overlap", result["by-overlap"])):
        lines += [
            "",
            f"By probe {title} (any@1 / any@5; a group under {MIN_GROUP} probes is unreliable)",
        ]
        for group, data in groups.items():
            flag = "  UNRELIABLE" if data["unreliable"] else ""
            cells = "  ".join(
                f"{name} {data[name]['any@1']:.2f}/{data[name]['any@5']:.2f}"
                for name in ("cairnkit", "cairnkit-whole-word", "strict", "keyword-count", "random")
            )
            lines.append(f"{group:<18} n={data['n']:<3} {cells}{flag}")
    lines += ["", "Paired comparison (bootstrap 95% interval of the difference; same probes)"]
    for c in result["paired"]:
        lines.append(
            f"{c['a']} - {c['b']} on {c['metric']}: {c['delta']:+.3f} "
            f"[{c['ci95'][0]:+.3f}, {c['ci95'][1]:+.3f}], n={c['n']}; "
            f"{c['a']} only right {c['a-only']}, {c['b']} only right {c['b-only']}"
        )
    for budget, rows in result.get("load", {}).items():
        lines += ["", f"Load with --budget {budget}"]
        lines += _grid(
            rows,
            [
                "gold@load",
                "gold-all@load",
                "stale-leak",
                "stale-loaded",
                "decoy-loaded",
                "facts",
                "n-stale",
            ],
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retrieval eval for `memory search` and `memory load`."
    )
    parser.add_argument("memory_folder", type=Path)
    parser.add_argument("probes", type=Path)
    parser.add_argument("--seed", type=int, default=0, help="seed of the random baseline")
    parser.add_argument(
        "--budget",
        type=int,
        action="append",
        help="load word budget; repeat for more (default 600)",
    )
    parser.add_argument("--no-load", action="store_true", help="skip the load part")
    parser.add_argument("--json", action="store_true", help="print JSON, not a table")
    args = parser.parse_args(argv)
    probes = read_probes(args.probes)
    result = report(args.memory_folder, probes, args.seed, args.budget or [600], not args.no_load)
    print(json.dumps(result, indent=2) if args.json else table(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
