"""Replay synthetic project traces through the real cairnkit load code, under forgetting policies.

Decision rule, written before the first run:
- A no-age policy wins if needed@load on vacation, old_trap and never_refine is at least the
  baselines' (paired seed difference outside 2 standard errors) and its stale share is at most
  10 points above the baselines'.
- If competition alone has a stale share above 40 percent with an agent that never refines, it
  cannot stand alone, and events or demotion must earn their place.
- A paired difference inside 2 standard errors is a tie, whatever the means say.

The load is the real `cairnkit.load.build_output`, with only its inputs stubbed: clock, branch,
changed paths, active set, usage. No Memory object is opened, so nothing reads or writes a real
memory folder.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cairnkit import followups, hygiene, load, ranking, selection, usage
from cairnkit.selection import clean, load_text, render, words_in

FIXTURE = Path(__file__).parents[1] / "fixtures" / "coding"
EPOCH = datetime(2026, 3, 1, 12, tzinfo=UTC)
TRANSIENT_SHARE = float(os.environ.get("TRANSIENT_SHARE", "0.35"))
SUPERSEDE_SHARE = 0.10
FILE_GONE_SHARE = 0.10
ORIG_SCORE_PARTS = selection.score_parts


def when(day: float) -> datetime:
    return EPOCH + timedelta(days=day)


@dataclass
class Spec:
    id: str
    kind: str
    text: str
    area: str
    day: int
    branch: str
    cls: str  # durable | transient | wrong
    stale_day: float | None = None
    superseded_day: float | None = None
    file_gone_day: float | None = None
    question: str | None = None


@dataclass
class LoadPoint:
    day: float
    branch: str
    diff_areas: list[str]
    needed: list[str]
    label: str


@dataclass
class World:
    specs: list[Spec] = field(default_factory=list)
    loads: list[LoadPoint] = field(default_factory=list)
    branch_end: dict[str, int] = field(default_factory=dict)
    lookups: list[tuple[float, str]] = field(default_factory=list)
    active: set[int] = field(default_factory=set)
    day_areas: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))


@dataclass(frozen=True)
class Policy:
    name: str
    capture: bool = False  # a write is a capture that must be refined, or its window ends it
    window: str | None = None  # cal | act
    window_days: int = 0
    agent_events: bool = True  # honours a supersede or until-merged the agent wrote
    tool_events: bool = True  # file gone (needs a known source)
    order: bool = False  # recency counts newer facts, not days
    home: bool = False  # +3 for a fact written on the current branch
    demote: bool = False  # no recency for a fact whose writing branch ended
    demote_zero: bool = False  # first version of demote: recency 0, so ties fall to oldest id
    nofold: bool = False  # no scenario lines: every shown fact shows its text
    use_rank: bool = False  # recency off, lookups count (no clock)
    trap_first: bool = (
        False  # +2 for a trap whose area the branch changed, so it beats newer facts there
    )
    use_end: int = 0  # retire after this many loads with no lookup and no relevance
    area_share: float = 1 / 3  # budget share that keeps one place per area with no signal
    control: str | None = None


POLICIES = [
    Policy("control:oracle", control="oracle"),
    Policy("control:random", control="random"),
    Policy("load"),
    Policy("no-area-places", area_share=0.0),
]
BY_NAME = {p.name: p for p in POLICIES}


class Pool:
    def __init__(self, rng: random.Random, pad: int = 0):
        rows = [json.loads(x) for x in (FIXTURE / "facts/main.jsonl").read_text().splitlines()]
        ended = {r["id"] for r in rows if r["type"] == "change"}
        facts = {r["id"]: r for r in rows if r["type"] == "fact"}
        probes = [json.loads(x) for x in (FIXTURE / "probes.jsonl").read_text().splitlines()]
        stale = {s for p in probes for s in p.get("stale_note_ids", [])}
        self.rng = rng
        self.pad = pad
        self.n = 0
        self.gold = []
        seen = set()
        for probe in probes:
            for gid in probe["gold_note_ids"]:
                f = facts[gid]
                if gid not in seen and f["kind"] != "rule" and gid not in stale:
                    seen.add(gid)
                    self.gold.append((f, probe["question"]))
        self.rng.shuffle(self.gold)
        self.bg = [
            f
            for i, f in facts.items()
            if i not in seen and i not in ended and i not in stale and f["kind"] != "rule"
        ]
        counts = Counter(f["area"] for f in facts.values())
        self.areas = [a for a, _ in counts.most_common(12)]
        self.weights = [1 / (i + 1) for i in range(len(self.areas))]

    def area(self, exclude=()) -> str:
        options = [
            (a, w) for a, w in zip(self.areas, self.weights, strict=False) if a not in exclude
        ]
        return self.rng.choices([a for a, _ in options], [w for _, w in options])[0]

    def next_id(self, day: int) -> str:
        self.n += 1
        return f"f-{when(day).strftime('%Y%m%d')}-{self.n:05x}"

    def text(self, base: str) -> str:
        self.n += 1
        text = f"{base} ref{self.n}"
        if self.pad:
            words = text.split()
            while len(words) < self.pad:
                words += self.rng.choice(self.bg)["text"].split()
            text = " ".join([*words[: self.pad - 1], f"ref{self.n}"])
        return text

    def gold_fact(self, world, day, branch, area=None, kind=None) -> Spec:
        for i, (f, question) in enumerate(self.gold):
            if area is None or f["area"] == area:
                self.gold.pop(i)
                spec = Spec(
                    self.next_id(day),
                    kind or f["kind"],
                    self.text(f["text"]),
                    area or f["area"],
                    day,
                    branch,
                    "durable",
                    question=question,
                )
                world.specs.append(spec)
                return spec
        f, question = self.gold.pop()
        spec = Spec(
            self.next_id(day),
            kind or f["kind"],
            self.text(f["text"]),
            area or f["area"],
            day,
            branch,
            "durable",
            question=question,
        )
        world.specs.append(spec)
        return spec

    def fact(self, world, day, branch, area, cls=None, horizon=400) -> Spec:
        cls = cls or ("transient" if self.rng.random() < TRANSIENT_SHARE else "durable")
        same = [f for f in self.bg if f["area"] == area] or self.bg
        f = self.rng.choice(same)
        base = f["text"] if cls == "durable" else f"In flight on this branch: {f['text']}"
        kind = f["kind"] if cls == "durable" else "event"
        spec = Spec(self.next_id(day), kind, self.text(base), area, day, branch, cls)
        if cls == "durable":
            roll = self.rng.random()
            if roll < SUPERSEDE_SHARE:
                spec.superseded_day = day + self.rng.randint(3, horizon)
                spec.stale_day = spec.superseded_day
            elif roll < SUPERSEDE_SHARE + FILE_GONE_SHARE:
                spec.file_gone_day = day + self.rng.randint(3, horizon)
                spec.stale_day = spec.file_gone_day
        world.specs.append(spec)
        return spec


def opaque(rng: random.Random, n: int = 0) -> str:
    return f"cursor/several-items-{rng.randrange(16**4):04x}{n}"


def history(world, pool, start, end, rate, exclude=(), hot=None, hot_share=0.0, weekdays=True):
    """Ordinary work: short branches in one area each, facts on active days."""
    rng = pool.rng
    day = start
    while day <= end:
        length = rng.randint(2, 5)
        area = hot if hot and rng.random() < hot_share else pool.area(exclude)
        branch = opaque(rng, day & 7)
        last = day
        for d in range(day, min(day + length, end + 1)):
            if weekdays and (d % 7) in (5, 6):
                continue
            world.active.add(d)
            world.day_areas[d].add(area)
            last = d
            for _ in range(rng.randint(max(rate - 1, 0), rate + 1)):
                pool.fact(world, d, branch, area)
        world.branch_end[branch] = last + 1
        day += length


def finish(world):
    """A transient note goes stale when its branch ends."""
    for s in world.specs:
        if s.cls == "transient" and s.branch in world.branch_end:
            s.stale_day = world.branch_end[s.branch]
    world.specs.sort(key=lambda s: s.day)
    world.loads.sort(key=lambda p: p.day)
    return world


def vacation(seed, rate, gap, pad=0):
    rng = random.Random(seed)
    pool, w = Pool(rng, pad), World()
    history(w, pool, -60, -1, rate)
    a = pool.area()
    b = opaque(rng, 9)
    w.active.update(range(-4, 1))
    trap = pool.gold_fact(w, -45, opaque(rng, 8), a, kind="trap")
    d1 = pool.gold_fact(w, -2, b, a)
    d2 = pool.gold_fact(w, -1, b)
    t1 = pool.fact(w, 0, b, a, cls="transient")
    for d in range(-4, 1):
        for _ in range(rate):
            pool.fact(w, d, b, a)
    back = gap + 1
    w.active.add(back)
    w.loads.append(LoadPoint(back, b, [a], [d1.id, d2.id, t1.id, trap.id], "same-branch"))
    w.loads.append(LoadPoint(back + 0.1, opaque(rng, 7), [], [d1.id, d2.id], "new-branch-no-diff"))
    return finish(w)


def busy_day(seed, rate, pad=0):
    rng = random.Random(seed)
    pool, w = Pool(rng, pad), World()
    history(w, pool, -60, 0, rate)
    a = pool.area()
    branches = [opaque(rng, i) for i in range(6)]
    trap = pool.gold_fact(w, -45, opaque(rng, 8), a, kind="trap")
    d1 = pool.gold_fact(w, 1, branches[0], a)
    d2 = pool.gold_fact(w, 1, branches[2])
    w.active.update({1, 2})
    for session in range(12):
        branch = branches[session % 6]
        area = a if session % 6 == 0 else pool.area((a,))
        for _ in range(6):
            pool.fact(w, 1, branch, area)
    w.loads.append(LoadPoint(1.9, branches[0], [a], [d1.id, trap.id], "session-12"))
    w.loads.append(LoadPoint(2, opaque(rng, 7), [], [d1.id, d2.id], "next-day-new-branch"))
    return finish(w)


def long_session(seed, rate, pad=0):
    rng = random.Random(seed)
    pool, w = Pool(rng, pad), World()
    history(w, pool, -60, 0, rate)
    a = pool.area()
    b, other = opaque(rng, 1), opaque(rng, 2)
    first = pool.gold_fact(w, 1, b, a)
    parallel = pool.gold_fact(w, 2, other, a)
    w.active.update(range(1, 7))
    notes = {}
    for d in range(1, 7):
        notes[d] = pool.fact(w, d, b, a, cls="transient")
        for _ in range(7):
            pool.fact(w, d, b, a)
        for _ in range(3):
            pool.fact(w, d, other, pool.area((a,)))
    for d in range(2, 7):
        need = [first.id, notes[d - 1].id] + ([parallel.id] if d > 2 else [])
        w.loads.append(LoadPoint(d + 0.9, b, [a], need, f"compaction-day-{d}"))
    return finish(w)


def workload(seed, rate, weeks=8, bias="uniform", pad=0, idle_weeks=0):
    """Mixed work. The next task needs two durable facts from its area, and the branch's note."""
    rng = random.Random(seed)
    pool, w = Pool(rng, pad), World()
    history(w, pool, -60, 7 * weeks, rate)
    by_branch = defaultdict(list)
    for s in w.specs:
        by_branch[s.branch].append(s)
    start_of = {b: min(x.day for x in v) for b, v in by_branch.items()}
    for branch, items in by_branch.items():
        start = start_of[branch]
        if start < 0 or start % 2:
            continue
        area = items[0].area
        for day, diff in ((start + 1, []), (start + 1.5, [area])):
            pool_old = [
                s
                for s in w.specs
                if s.area == area
                and s.cls == "durable"
                and s.day < day
                and (s.stale_day is None or s.stale_day > day)
            ]
            if bias == "recent":
                pool_old = sorted(pool_old, key=lambda s: -s.day)[:8]
            need = [s.id for s in rng.sample(pool_old, min(2, len(pool_old)))]
            notes = [s for s in items if s.cls == "transient" and s.day < day]
            if notes:
                need.append(rng.choice(notes).id)
            if need:
                w.loads.append(
                    LoadPoint(day, branch, diff, need, "no-diff" if not diff else "diff")
                )
            for s in pool_old[:1]:
                if rng.random() < 0.3:
                    w.lookups.append((day + 0.2, s.id))
    return finish(w)


def old_trap(seed, rate, hot_share=0.0, pad=0, last=149):
    rng = random.Random(seed)
    pool, w = Pool(rng, pad), World()
    a = pool.area()
    trap = pool.gold_fact(w, 0, opaque(rng, 8), a, kind="trap")
    dec = pool.gold_fact(w, 2, opaque(rng, 8), a)
    w.active.update({0, 2})
    if hot_share:
        history(w, pool, 3, last, rate, hot=a, hot_share=hot_share)
    else:
        history(w, pool, 3, last, rate, exclude=(a,))
    need = [trap.id, dec.id]
    w.active.add(150)
    w.loads.append(LoadPoint(150, opaque(rng, 7), [], need, "opaque-branch-no-diff"))
    w.loads.append(LoadPoint(150.1, f"fix-{a}-retry", [], need, "descriptive-branch-no-diff"))
    w.loads.append(LoadPoint(150.2, opaque(rng, 6), [a], need, "after-first-commit"))
    w.loads.append(LoadPoint(150.3, opaque(rng, 5), ["unmappedpath"], need, "label-mismatch"))
    w.loads.append(LoadPoint(150.4, opaque(rng, 4), [], [trap.id], "trap-only:no-signal"))
    w.loads.append(LoadPoint(150.5, opaque(rng, 3), [a], [trap.id], "trap-only:after-first-commit"))
    return finish(w)


def wrong_fact(seed, rate, variant="none", kind="fact", pad=0):
    rng = random.Random(seed)
    pool, w = Pool(rng, pad), World()
    a = pool.areas[0]
    wrong = pool.gold_fact(w, 1, opaque(rng, 8), a, kind=kind)
    wrong.cls = "wrong"
    wrong.stale_day = 1
    if variant == "file_gone":
        wrong.file_gone_day = 40
    elif variant == "contradicted":
        wrong.superseded_day = 40
        pool.gold_fact(w, 40, opaque(rng, 7), a)
    history(w, pool, 2, 120, rate, hot=a, hot_share=0.4)
    probe_days = range(3, 121, 3)
    for d in probe_days:
        here = a if d % 2 else pool.area((a,))
        diff = [here] if d % 4 else []
        w.loads.append(
            LoadPoint(
                d + 0.5,
                opaque(rng, d % 9),
                diff,
                [],
                f"day-{'0-14' if d <= 14 else '15-60' if d <= 60 else '61+'}",
            )
        )
    return finish(w)


def captured(world, share, seed):
    """The agent wrote only this share of what happened. A need it did not write cannot load."""
    rng = random.Random(seed * 31 + 5)
    world.specs = [x for x in world.specs if rng.random() < share]
    live = {x.id for x in world.specs}
    world.lookups = [x for x in world.lookups if x[1] in live]
    return world


SCENARIOS = {
    "vacation-gap0": lambda s, r, p: vacation(s, r, 0, p),
    "vacation-gap14": lambda s, r, p: vacation(s, r, 14, p),
    "vacation-gap60": lambda s, r, p: vacation(s, r, 60, p),
    "busy-day": busy_day,
    "long-session": long_session,
    "workload-uniform": lambda s, r, p: workload(s, r, pad=p),
    "workload-recent": lambda s, r, p: workload(s, r, bias="recent", pad=p),
    "old-trap": old_trap,
    "old-trap-hot-area": lambda s, r, p: old_trap(s, r, 0.35, p),
    "old-trap-idle30": lambda s, r, p: old_trap(s, r, 0.0, p, last=120),
    "capture-100": lambda s, r, p: captured(workload(s, r, pad=p), 1.0, s),
    "capture-50": lambda s, r, p: captured(workload(s, r, pad=p), 0.5, s),
    "capture-25": lambda s, r, p: captured(workload(s, r, pad=p), 0.25, s),
    "wrong-silent": lambda s, r, p: wrong_fact(s, r, "none", pad=p),
    "wrong-silent-trap": lambda s, r, p: wrong_fact(s, r, "none", "trap", p),
    "wrong-contradicted": lambda s, r, p: wrong_fact(s, r, "contradicted", pad=p),
    "wrong-file-gone": lambda s, r, p: wrong_fact(s, r, "file_gone", pad=p),
}


def rolls(world, p, seed):
    """Whether the agent does its part for each fact. The same seed gives the same rolls."""
    rng = random.Random(seed * 7919 + 13)
    return {s.id: rng.random() < p for s in sorted(world.specs, key=lambda x: x.id)}


def active_days_between(world, start, end):
    return sum(1 for d in world.active if start < d <= end)


def visible(spec: Spec, t: float, pol: Policy, did: bool, world: World) -> str | None:
    """The state of a fact at t: None when ended, else 'long' or 'short'."""
    if spec.day > t:
        return None
    scope = "long"
    if pol.capture and not did:
        age = t - spec.day if pol.window == "cal" else active_days_between(world, spec.day, t)
        if age >= pol.window_days:
            return None
    if pol.agent_events and did:
        if spec.superseded_day is not None and t >= spec.superseded_day:
            return None
        if spec.cls == "transient":
            end = world.branch_end.get(spec.branch)
            if end is not None and t >= end:
                return None
            scope = "short"
    if pol.tool_events and spec.file_gone_day is not None and t >= spec.file_gone_day:
        return None
    return scope


def to_state(spec: Spec, scope: str, pol: Policy) -> dict:
    state = {
        "type": "fact",
        "id": spec.id,
        "kind": spec.kind,
        "text": spec.text,
        "area": spec.area,
        "happened_at": when(spec.day).date().isoformat(),
        "learned_at": when(spec.day).isoformat(),
        "source": "session:x",
        "basis": "seen",
        "status": "active",
        "scope": scope,
        "writer": spec.branch,
        "links": [],
        "history": [],
    }
    if scope == "short":
        state["until_branch_merged"] = spec.branch
    return state


def patched_parts(pol, ctx):
    def parts(state, moment, areas, words, used_at=None):
        out = ORIG_SCORE_PARTS(state, moment, areas, words, used_at)
        fid = state.get("id")
        if pol.order:
            out["recency"] = 2.0 * 0.5 ** (ctx["newer"].get(fid, 0) / 30)
        if pol.use_rank:
            out["recency"] = 1e-6 * ctx["newer_inv"].get(fid, 0)
            out["use"] = min(3.0, 1.0 * ctx["count"].get(fid, 0))
        if pol.trap_first and state.get("kind") == "trap" and out["area"]:
            out["trap_first"] = 2.0
        if pol.home and state.get("writer") == ctx["branch"]:
            out["home"] = 3.0
        if pol.demote and state.get("writer") != ctx["branch"]:
            end = ctx["branch_end"].get(state.get("writer"))
            if end is not None and ctx["t"] >= end:
                out["recency"] = 0.0 if pol.demote_zero else out["recency"] * 0.25
        return out

    return parts


def run_load(states, specs, point, pol, ctx, budget, rng):
    if pol.control == "oracle":
        chosen = [s for s in states if s["id"] in point.needed]
        return {s["id"] for s in chosen}, set(), 0, len(chosen)
    if pol.control in ("random", "oldest"):
        order = list(states)
        if pol.control == "random":
            rng.shuffle(order)
        else:
            order.sort(key=lambda s: s["id"])
        used, shown = 0, set()
        for s in order:
            cost = words_in(render(s))
            if used + cost <= budget:
                shown.add(s["id"])
                used += cost
        return shown, set(), 0, len(shown)
    memory = SimpleNamespace(
        project=SimpleNamespace(root=Path("/nonexistent"), is_git=False),
        dir=Path("/nonexistent"),
        states={},
        secret_notes=list,
        env=None,
        errors=[],
        config={"areas": {}},
    )
    with (
        patch.multiple(selection, score_parts=patched_parts(pol, ctx), AREA_SHARE=pol.area_share),
        patch.multiple(
            load,
            now=lambda: when(point.day),
            current_branch=lambda root: point.branch,
            writer_name=lambda root: point.branch,
            changed_paths=lambda root, branch: [f"{a}/x.py" for a in point.diff_areas],
            active_states=lambda memory: states,
            note_head=lambda path, env: [],
        ),
        patch.object(usage, "last_used", lambda memory: ctx["used_at"]),
        patch.object(hygiene, "hygiene_line", lambda memory: None),
        patch.object(followups, "pending_line", lambda memory: None),
    ):
        lines = load.build_output(memory, None, budget)
    text = "\n".join(lines)
    shown_text, shown_id = set(), set()
    for s in states:
        if clean(load_text(s)) in text:
            shown_text.add(s["id"])
        elif s["id"] in text:
            shown_id.add(s["id"])
    id_words = sum(words_in(x) for x in lines if x.startswith("- ") and " | " in x)
    return shown_text, shown_id, id_words, len(shown_text)


def search_hit(states, spec, query):
    terms = ranking.query_terms(query)
    ranked = ranking.rank_facts(states, terms)
    return spec.id in {s["id"] for s, _ in ranked[:5]}


def replay(world: World, pol: Policy, p: float, seed: int, budget: int):
    did = rolls(world, p, seed)
    spec_by_id = {s.id: s for s in world.specs}
    rng = random.Random(seed + 1)
    rows = []
    lookups = sorted(world.lookups)
    active_days = sorted(world.active)
    retire_day: dict[str, float | None] = {}

    def retires_on(spec):
        """Two sessions per active day. The count resets when the fact's area is worked on or it is looked up."""
        if spec.id in retire_day:
            return retire_day[spec.id]
        looked = {int(day) for day, fid in lookups if fid == spec.id}
        idle, found = 0, None
        for day in active_days:
            if day <= spec.day:
                continue
            if spec.area in world.day_areas.get(day, ()) or day in looked:
                idle = 0
                continue
            idle += 2
            if idle >= pol.use_end:
                found = day
                break
        retire_day[spec.id] = found
        return found

    for _index, point in enumerate(world.loads):
        t = point.day
        used_at, count = {}, Counter()
        for day, fid in lookups:
            if day <= t and spec_by_id[fid].day <= t:
                used_at[fid] = when(day)
                count[fid] += 1
        states = []
        for s in world.specs:
            if s.day > t:
                continue
            if pol.use_end:
                gone = retires_on(s)
                if gone is not None and gone <= t:
                    continue
            scope = visible(s, t, pol, did[s.id], world)
            if scope:
                states.append(to_state(s, scope, pol))
        ordered = sorted(states, key=lambda s: s["learned_at"])
        n = len(ordered)
        ctx = {
            "newer": {s["id"]: n - 1 - i for i, s in enumerate(ordered)},
            "newer_inv": {s["id"]: i for i, s in enumerate(ordered)},
            "count": count,
            "used_at": used_at,
            "branch": point.branch,
            "branch_end": world.branch_end,
            "t": t,
        }
        shown_text, shown_id, id_words, n_text = run_load(
            states, world.specs, point, pol, ctx, budget, rng
        )
        total = sum(words_in(load_text(s)) for s in states if s["id"] in shown_text)
        stale = 0
        for s in states:
            sp = spec_by_id[s["id"]]
            if s["id"] in shown_text and sp.stale_day is not None and t >= sp.stale_day:
                stale += words_in(load_text(s))
        wrong = any(spec_by_id[i].cls == "wrong" for i in shown_text)
        need = point.needed
        live = {s["id"] for s in states}
        row = {
            "label": point.label,
            "n_need": len(need),
            "text": sum(1 for i in need if i in shown_text),
            "id_only": sum(1 for i in need if i in shown_id),
            "alive": sum(1 for i in need if i in live),
            "stale": stale,
            "total": total,
            "n_text": n_text,
            "id_words": id_words,
            "wrong": wrong,
            "n_states": len(states),
        }
        questions = [spec_by_id[i] for i in need if i in spec_by_id and spec_by_id[i].question]
        if questions and pol.control is None:
            row["search_n"] = len(questions)
            row["search_hit"] = sum(
                1 for sp in questions if sp.id in live and search_hit(states, sp, sp.question)
            )
        rows.append(row)
    facts = len(world.specs)
    refines = sum(1 for s in world.specs if did[s.id]) if pol.capture else 0
    horizon = world.loads[-1].day if world.loads else 0
    ev = 0
    if pol.agent_events:
        for s in world.specs:
            if did[s.id] and s.superseded_day is not None and s.superseded_day <= horizon:
                ev += 1
    return {"rows": rows, "facts": facts, "actions": refines + ev}


def job(args):
    scenario, pname, p, seed, rate, budget, pad = args
    world = SCENARIOS[scenario](seed, rate, pad)
    out = replay(world, BY_NAME[pname], p, seed, budget)
    return scenario, pname, p, seed, out


def summarize(results):
    grouped = defaultdict(list)
    for scenario, pname, p, seed, out in results:
        grouped[(scenario, pname, p)].append((seed, out))
    rows = []
    for (scenario, pname, p), runs in sorted(grouped.items()):
        labels = sorted({r["label"] for _, o in runs for r in o["rows"]})
        for label in ["ALL", *labels]:
            need, id_only, alive, stale, wrong, facts, search = [], [], [], [], [], [], []
            for _, o in runs:
                rs = [r for r in o["rows"] if label == "ALL" or r["label"] == label]
                n = sum(r["n_need"] for r in rs)
                if n:
                    need.append(sum(r["text"] for r in rs) / n)
                    id_only.append(sum(r["id_only"] for r in rs) / n)
                    alive.append(sum(r["alive"] for r in rs) / n)
                t = sum(r["total"] for r in rs)
                stale.append(sum(r["stale"] for r in rs) / t if t else 0)
                wrong.append(sum(1 for r in rs if r["wrong"]) / len(rs) if rs else 0)
                facts.append(sum(r["n_text"] for r in rs) / len(rs) if rs else 0)
                sn = sum(r.get("search_n", 0) for r in rs)
                if sn:
                    search.append(sum(r.get("search_hit", 0) for r in rs) / sn)
            actions = [100 * o["actions"] / max(o["facts"], 1) for _, o in runs]

            def mean(v):
                return statistics.mean(v) if v else float("nan")

            def se(v):
                return statistics.stdev(v) / math.sqrt(len(v)) if len(v) > 1 else 0.0

            rows.append(
                {
                    "scenario": scenario,
                    "policy": pname,
                    "p": p,
                    "label": label,
                    "seeds": len(runs),
                    "needed": mean(need),
                    "needed_se": se(need),
                    "needed_min": min(need, default=float("nan")),
                    "needed_max": max(need, default=float("nan")),
                    "id_only": mean(id_only),
                    "alive": mean(alive),
                    "stale": mean(stale),
                    "stale_se": se(stale),
                    "wrong": mean(wrong),
                    "facts_shown": mean(facts),
                    "search5": mean(search),
                    "actions_per_100": mean(actions),
                }
            )
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--rate", type=int, default=4)
    ap.add_argument("--budget", type=int, default=600)
    ap.add_argument("--pad", type=int, default=0)
    ap.add_argument("--p", type=float, nargs="+", default=[0.0, 1.0])
    ap.add_argument("--scenarios", nargs="*", default=list(SCENARIOS))
    ap.add_argument("--policies", nargs="*", default=[x.name for x in POLICIES])
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=6)
    a = ap.parse_args()
    jobs = [
        (s, n, p, seed, a.rate, a.budget, a.pad)
        for s in a.scenarios
        for n in a.policies
        for p in a.p
        for seed in range(a.seeds)
    ]
    with mp.get_context("fork").Pool(a.procs) as pool:
        results = pool.map(job, jobs, chunksize=4)
    rows = summarize(results)
    raw = [
        {
            "scenario": s,
            "policy": n,
            "p": p,
            "seed": seed,
            "rows": o["rows"],
            "facts": o["facts"],
            "actions": o["actions"],
        }
        for s, n, p, seed, o in results
    ]
    Path(a.out).write_text(json.dumps({"args": vars(a), "summary": rows, "raw": raw}))
    print(f"wrote {a.out}: {len(jobs)} runs", file=sys.stderr)


if __name__ == "__main__":
    main()
