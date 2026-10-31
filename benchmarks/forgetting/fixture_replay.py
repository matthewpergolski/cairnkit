"""The coding fixture as written, no resampling: does the shown text hold the answer?

Reproduces the published gold@load, then separates "the text is shown" from "only the id is".
Tests a demotion that needs no agent action: when a newer fact in the same area shares enough
words with an older one, the older one loses its score but stays active and searchable.
"""

from __future__ import annotations

import json
import statistics

import harness as h

from cairnkit import load, scenarios, selection, usage
from cairnkit.clock import parse_time
from cairnkit.selection import clean, load_text
from cairnkit.similar import analyze, overlap

NOW = "2026-10-03T12:00:00+00:00"
ROWS = [json.loads(x) for x in (h.FIXTURE / "facts/main.jsonl").read_text().splitlines()]
FACTS = {r["id"]: r for r in ROWS if r["type"] == "fact"}
ENDED = {r["id"] for r in ROWS if r["type"] == "change"}
PROBES = [json.loads(x) for x in (h.FIXTURE / "probes.jsonl").read_text().splitlines()]
STALE = {s for p in PROBES for s in p.get("stale_note_ids", [])}
WORDS = {i: analyze(f["text"]) for i, f in FACTS.items()}


def demoted(ids, threshold):
    out = set()
    for a in ids:
        for b in ids:
            if a == b or FACTS[a]["area"] != FACTS[b]["area"]:
                continue
            if FACTS[b]["learned_at"] > FACTS[a]["learned_at"]:
                if overlap(WORDS[a].tokens, WORDS[b].tokens) >= threshold:
                    out.add(a)
    return out


def run(budget, nofold, honour_supersede, threshold, diff_area=None, recency=True, moment=NOW):
    ids = [
        i for i, f in FACTS.items() if f["kind"] != "rule" and not (honour_supersede and i in ENDED)
    ]
    low = demoted(ids, threshold) if threshold else set()
    states = [{**FACTS[i], "links": [], "history": [], "scope": "long"} for i in ids]

    def parts(state, when, areas, words, used_at=None):
        out = h.ORIG_SCORE_PARTS(state, when, areas, words, used_at)
        if state["id"] in low:
            out = {k: 0.0 for k in out}
        return out

    selection.score_parts = parts
    scenarios.group_scenarios = (lambda *a, **k: []) if nofold else h.ORIG_GROUPS
    load.now = lambda: parse_time(moment)
    load.current_branch = lambda root: "work"
    load.writer_name = lambda root: "work"
    load.changed_paths = lambda root, branch: [f"{diff_area}/x.py"] if diff_area else []
    load.active_states = lambda memory: states
    usage.last_used = lambda memory: {}
    h.hygiene.hygiene_line = lambda memory: None
    h.followups.pending_line = lambda memory: None
    load._followup_pending = lambda memory: False
    load.note_head = lambda path: []
    memory = h.SimpleNamespace(
        project=h.SimpleNamespace(root=h.Path("/nonexistent")),
        dir=h.Path("/nonexistent"),
        states={},
        errors=[],
        config={"areas": {}},
    )
    text = "\n".join(load.build_output(memory, None, budget))
    shown_text = {s["id"] for s in states if clean(load_text(s)) in text}
    shown_any = shown_text | {s["id"] for s in states if s["id"] in text}
    return shown_text, shown_any, text


def score(nofold, honour, threshold, budget=600):
    no_diff_text, _, _ = run(budget, nofold, honour, threshold)
    _, no_diff_any, _ = run(budget, nofold, honour, threshold)
    probes = [p for p in PROBES if not all(FACTS[g]["kind"] == "rule" for g in p["gold_note_ids"])]
    hit_text = sum(1 for p in probes if set(p["gold_note_ids"]) & no_diff_text) / len(probes)
    hit_any = sum(1 for p in probes if set(p["gold_note_ids"]) & no_diff_any) / len(probes)
    diff_hits = []
    leaks = []
    for p in probes:
        area = FACTS[p["gold_note_ids"][0]]["area"]
        shown, _, _ = run(budget, nofold, honour, threshold, diff_area=area)
        diff_hits.append(bool(set(p["gold_note_ids"]) & shown))
        leaks.append(len(STALE & shown))
    stale_shown = len(STALE & no_diff_text)
    return (
        hit_any,
        hit_text,
        statistics.mean(diff_hits),
        stale_shown,
        statistics.mean(leaks),
        len(no_diff_text),
    )


def main():
    print("budget 600. gold@any counts an id line as loaded (the published measure).")
    print(
        "variant                                  gold@any gold@text gold@text+area stale-noDiff stale+area shown"
    )
    for name, nofold, honour, threshold in [
        ("real load, agent links nothing", False, False, 0),
        ("real load, agent superseded the 7", False, True, 0),
        ("no fold, agent links nothing", True, False, 0),
        ("no fold, agent superseded the 7", True, True, 0),
        ("no fold, overlap-demote .25, no agent", True, False, 0.25),
        ("real load, overlap-demote .25, no agent", False, False, 0.25),
    ]:
        row = score(nofold, honour, threshold)
        print(
            f"{name:40} {row[0]:8.2f} {row[1]:9.2f} {row[2]:14.2f} {row[3]:11d} {row[4]:10.2f} {row[5]:5d}"
        )
    print(
        "reconcile with benchmarks/retrieval_eval.py: clock 2026-10-20, all probes, rules count, ended excluded"
    )
    rules = {i for i, f in FACTS.items() if f["kind"] == "rule"}
    text, anyid, _ = run(600, False, True, 0, moment="2026-10-20T12:00:00+00:00")
    shown_any = anyid | rules
    shown_text = text | rules
    print(
        "  gold@any",
        round(sum(1 for p in PROBES if set(p["gold_note_ids"]) & shown_any) / len(PROBES), 2),
        "gold@text",
        round(sum(1 for p in PROBES if set(p["gold_note_ids"]) & shown_text) / len(PROBES), 2),
        "facts any",
        len(anyid),
        "facts text",
        len(text),
    )
    print("budget sweep, gold@text with area signal")
    for budget in (300, 600, 1200):
        fold = score(False, False, 0, budget)
        flat = score(True, False, 0.25, budget)
        print(
            f"{budget}: real {fold[1]:.2f}/{fold[2]:.2f}  no-fold+demote {flat[1]:.2f}/{flat[2]:.2f}"
        )
    _shown, _, text = run(600, False, False, 0)
    print("--- sample of the real load, scenario section ---")
    lines = text.splitlines()
    start = next((i for i, x in enumerate(lines) if x.startswith("## Scenarios")), 0)
    print("\n".join(x[:150] for x in lines[start : start + 10]))


if __name__ == "__main__":
    main()
