"""Auto-tidy retires a near duplicate when the meaning matches, and only then."""

from __future__ import annotations

import io
import itertools
import json
import random
import string

from conftest import make_fact, write_facts

from cairnkit import autotidy, similar
from cairnkit.autotidy import _near_duplicates, outranks
from cairnkit.cli import main
from cairnkit.similar import analyze, exact_key, similarity

NOW = "2026-10-20T12:00:00+00:00"
OLD = "2026-10-17T12:00:00+00:00"
A, B = "f-20261001-0001", "f-20261002-0002"


def auto(capsys):
    capsys.readouterr()
    code = main(["tidy", "--auto"])
    return code, capsys.readouterr().out


def status_of(fid):
    from cairnkit.memory import Memory
    from cairnkit.paths import find_project

    return Memory.open(find_project(), None).states[fid]


def test_near_duplicate_with_the_same_meaning_is_superseded(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(A, "The cache must be warmed before the release job runs."),
            make_fact(B, "The cache must be warmed before the release job runs now."),
        ],
    )
    code, _ = auto(capsys)
    assert code == 0
    old = status_of(A)
    assert old["status"] == "superseded"
    assert old["superseded_by"] == B
    log = (mem / "auto-tidy.log").read_text()
    assert "similar_to" in log


def test_a_near_pair_with_a_different_meaning_stays_active(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(A, "The cache must be warmed before the release job runs."),
            make_fact(B, "The cache must not be warmed before the release job runs."),
        ],
    )
    auto(capsys)
    assert status_of(A)["status"] == "active"
    assert status_of(B)["status"] == "active"


def _facts(count: int, vocabulary: int, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    # Letters only: a word with a digit counts as a number, so a pair that differs in it never
    # matches.
    words = ["".join(pair) for pair in itertools.product(string.ascii_lowercase, repeat=3)]
    words = words[:vocabulary]
    return [
        make_fact(
            f"f-20261001-{i:04x}",
            " ".join(rng.sample(words, rng.randint(10, 12))),
            kind=rng.choice(["fact", "trap"]),
            basis=rng.choice(["seen", "seen", "told"]),
            learned_at=f"2026-10-{rng.randint(1, 3):02d}T12:00:00+00:00",
        )
        for i in range(count)
    ]


def _retired_when_each_pair_is_checked(facts: list[dict]) -> set[tuple[str, str, str]]:
    found = set()
    for kind in {f["kind"] for f in facts}:
        ordered = sorted(
            (f for f in facts if f["kind"] == kind), key=lambda s: (s["learned_at"], s["id"])
        )
        for i, older in enumerate(ordered):
            best = None
            for newer in ordered[i + 1 :]:
                if exact_key(older["text"]) == exact_key(newer["text"]) or outranks(older, newer):
                    continue
                score = similarity(analyze(older["text"]), analyze(newer["text"]))
                if score is not None and (best is None or score > best[0]):
                    best = (score, newer)
            if best:
                found.add((older["id"], best[1]["id"], f"{best[0]:.0%}"))
    return found


def test_near_repeats_are_the_same_as_when_each_pair_is_checked():
    for seed in range(5):
        facts = _facts(150, 13, seed)
        expected = _retired_when_each_pair_is_checked(facts)
        assert expected, "the fixture must hold near repeats"
        got = {
            (r.id, r.superseded_by, r.reason.split("(")[1].split(" ")[0])
            for r in _near_duplicates(facts, set())
        }
        assert got == expected


def test_a_large_memory_does_not_compare_each_pair(monkeypatch):
    calls = []
    real = similar.similarity

    def counted(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(similar, "similarity", counted)
    monkeypatch.setattr(autotidy, "similarity", counted, raising=False)
    _near_duplicates(_facts(2000, 3000), set())
    assert len(calls) < (2000 * 1999 // 2) / 100


def test_facts_with_few_distinct_words_stop_at_the_comparison_limit(monkeypatch):
    calls = []
    real = similar.similarity

    def counted(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(similar, "similarity", counted)
    _near_duplicates(_facts(2000, 13), set())
    assert len(calls) <= 2 * similar.MAX_COMPARISONS  # one limit for each kind in the fixture


def test_stop_tidies_when_the_tidy_state_is_old(repo, mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    (mem / "config.toml").write_text('auto_tidy = "on"\n')
    write_facts(
        mem,
        [
            make_fact(A, "Deploys need a clean tree.", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(B, "deploys need a CLEAN tree!", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    (mem / ".auto-tidy-state.json").write_text(
        json.dumps({"last_tidy_at": OLD, "started_at": OLD, "sessions": 1})
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    capsys.readouterr()
    assert main(["hook", "stop", "--agent", "generic"]) == 0
    assert status_of(A)["status"] == "superseded"
    assert status_of(A)["superseded_by"] == B
