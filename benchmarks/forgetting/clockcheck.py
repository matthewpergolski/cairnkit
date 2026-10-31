"""Does the load change when only the clock moves? Same facts, no writes, later clock.

Answers whether the recency term is a hidden age limit, and which part of the code moves the set.
Also measures the near-repeat detector on real fixture pairs, at weaker thresholds, as a demotion
signal that needs no agent action.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict

import harness as h

from cairnkit.similar import analyze, overlap, similarity

GAPS = [14, 30, 60, 90, 120, 365]
VARIANTS = {
    "real": h.Policy("real", agent_events=False, tool_events=False),
    "no-fold": h.Policy("nofold", agent_events=False, tool_events=False, nofold=True),
    "write-order": h.Policy("order", agent_events=False, tool_events=False, order=True),
}


def load_at(world, day, pol, branch="main", diff=()):
    states = [h.to_state(s, "long", pol) for s in world.specs if s.day <= day]
    ordered = sorted(states, key=lambda s: s["learned_at"])
    n = len(ordered)
    ctx = {
        "newer": {s["id"]: n - 1 - i for i, s in enumerate(ordered)},
        "newer_inv": {s["id"]: i for i, s in enumerate(ordered)},
        "count": {},
        "used_at": {},
        "branch": branch,
        "branch_end": {},
        "t": day,
    }
    point = h.LoadPoint(day, branch, list(diff), [], "x")
    return h.run_load(states, world.specs, point, pol, ctx, 600, None)[0]


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 1.0


def clock_sweep(seeds=30):
    rows = defaultdict(list)
    newest = defaultdict(list)
    for seed in range(seeds):
        world = h.vacation(seed, 4, 0)
        base_day = max(s.day for s in world.specs) + 1
        {s.id: s for s in world.specs}
        recent = {s.id for s in sorted(world.specs, key=lambda s: -s.day)[:40]}
        for name, pol in VARIANTS.items():
            base = load_at(world, base_day, pol)
            for gap in GAPS:
                later = load_at(world, base_day + gap, pol)
                rows[(name, gap)].append(jaccard(base, later))
                newest[(name, gap)].append(len(later & recent) / max(len(later), 1))
    print("clock moves, nothing written. Jaccard of shown text against the load before the gap")
    print("variant      " + " ".join(f"gap{g:>4}" for g in GAPS))
    for name in VARIANTS:
        print(f"{name:12} " + " ".join(f"{statistics.mean(rows[(name, g)]):7.2f}" for g in GAPS))
    print("min over seeds")
    for name in VARIANTS:
        print(f"{name:12} " + " ".join(f"{min(rows[(name, g)]):7.2f}" for g in GAPS))
    print("share of the load that is among the 40 newest facts")
    for name in VARIANTS:
        print(f"{name:12} " + " ".join(f"{statistics.mean(newest[(name, g)]):7.2f}" for g in GAPS))


def fold_loss(seeds=30):
    """How many active facts does the real load drop from text because of scenario folding?"""
    swallowed, offered, words_ids, _words_all = [], [], [], []
    for seed in range(seeds):
        world = h.workload(seed, 4)
        day = max(s.day for s in world.specs) + 1
        pol = VARIANTS["real"]
        states = [h.to_state(s, "long", pol) for s in world.specs]
        ctx = {
            "newer": {},
            "newer_inv": {},
            "count": {},
            "used_at": {},
            "branch": "main",
            "branch_end": {},
            "t": day,
        }
        point = h.LoadPoint(day, "main", [], [], "x")
        text, ids, id_words, _ = h.run_load(states, world.specs, point, pol, ctx, 600, None)
        h.ORIG_GROUPS(states, h.when(day), set(), set(), {})
        swallowed.append(len(ids))
        offered.append(len(text))
        words_ids.append(id_words)
    print(
        f"fold: text shown {statistics.mean(offered):.1f}, id only {statistics.mean(swallowed):.1f}, "
        f"words on id lines {statistics.mean(words_ids):.0f} of 600"
    )


def stale_pairs():
    root = h.FIXTURE
    rows = [json.loads(x) for x in (root / "facts/main.jsonl").read_text().splitlines()]
    facts = {r["id"]: r for r in rows if r["type"] == "fact"}
    probes = [json.loads(x) for x in (root / "probes.jsonl").read_text().splitlines()]
    pairs = {
        (s, g) for p in probes for s in p.get("stale_note_ids", []) for g in p["gold_note_ids"]
    }
    words = {i: analyze(f["text"]) for i, f in facts.items()}
    detected = sum(1 for s, g in pairs if similarity(words[s], words[g]) is not None)
    print(f"real similarity() on stale pairs: {detected} of {len(pairs)}")
    ids = list(facts)
    print("threshold  same-area pairs flagged  true pairs caught  false pairs")
    for threshold in (0.5, 0.4, 0.3, 0.25, 0.2):
        tp = fp = 0
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                if facts[a]["area"] != facts[b]["area"]:
                    continue
                if overlap(words[a].tokens, words[b].tokens) >= threshold:
                    if (a, b) in pairs or (b, a) in pairs:
                        tp += 1
                    else:
                        fp += 1
        print(f"{threshold:9} {tp + fp:24} {tp:18} {fp:12}")


if __name__ == "__main__":
    clock_sweep()
    fold_loss()
    stale_pairs()
