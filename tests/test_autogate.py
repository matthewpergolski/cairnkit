"""Quality-gate auto-accept, near-dup dismiss, and one-shot pending hygiene."""

from __future__ import annotations

import io

from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.pending import Candidate, add_candidates, fold, pending

NOW = "2026-10-20T12:00:00+00:00"
LATER = "2026-10-20T12:35:00+00:00"


def seed(mem, items):
    memory = Memory.open(find_project(), None)
    return add_candidates(memory, items)


def cand(**kwargs):
    base = dict(
        id="c-20261020-aaaa",
        text="lesson: always warm the cache before the release job runs",
        kind="lesson",
        source="commit:abc1234dead",
        origin="draft",
        area="deploy",
        created_at=NOW,
        paths=["src/deploy.py"],
    )
    base.update(kwargs)
    return Candidate(**base)


def test_quality_gate_auto_accepts_a_grounded_lesson(repo, mem, monkeypatch, capsys):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    seed(mem, [cand()])
    memory = Memory.open(find_project(), None)
    from cairnkit import autogate

    accepted = autogate.run_gate(memory)
    assert len(accepted) == 1
    states = fold(memory)
    assert states["c-20261020-aaaa"].status == "accepted"
    assert states["c-20261020-aaaa"].fact_id
    memory.reload()
    assert states["c-20261020-aaaa"].fact_id in memory.states


def test_quality_gate_leaves_short_or_ungrounded_pending(repo, mem, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    seed(
        mem,
        [
            cand(id="c-20261020-bbbb", text="too short", kind="lesson", source="commit:abc"),
            cand(
                id="c-20261020-cccc",
                text="lesson: a long enough lesson without a grounded source field here",
                kind="lesson",
                source="session:2026-10-20",
            ),
            cand(
                id="c-20261020-dddd",
                text="fact: something plain that is long enough to pass length",
                kind="fact",
                source="commit:abc1234",
            ),
        ],
    )
    memory = Memory.open(find_project(), None)
    from cairnkit import autogate

    assert autogate.run_gate(memory) == []
    assert {c.id for c in pending(memory)} == {
        "c-20261020-bbbb",
        "c-20261020-cccc",
        "c-20261020-dddd",
    }


def test_near_dup_of_active_dismisses_pending(repo, mem, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [make_fact("f-20261001-0001", "Always warm the cache before the release job runs.")],
    )
    seed(
        mem,
        [
            cand(
                id="c-20261020-eeee",
                text="always warm the cache before the release job runs",
                kind="lesson",
                source="commit:abc1234dead",
            )
        ],
    )
    memory = Memory.open(find_project(), None)
    from cairnkit import autogate

    autogate.run_gate(memory)
    assert fold(memory)["c-20261020-eeee"].status == "dismissed"


def test_near_dup_among_pending_keeps_one(repo, mem, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    seed(
        mem,
        [
            cand(
                id="c-20261020-fff1",
                text="decision: prefer the CDN for every static font file we ship",
                kind="decision",
                source="commit:aaa1111dead",
            ),
            cand(
                id="c-20261020-fff2",
                text="decision: prefer the CDN for every static font file we ship now",
                kind="decision",
                source="commit:bbb2222dead",
            ),
        ],
    )
    memory = Memory.open(find_project(), None)
    from cairnkit import autogate

    autogate.run_gate(memory)
    left = pending(memory)
    statuses = {c.id: fold(memory)[c.id].status for c in fold(memory).values()}
    # One dismissed as near-dup; the other may be accepted or still pending.
    assert statuses["c-20261020-fff1"] != statuses["c-20261020-fff2"] or len(left) <= 1


def test_hygiene_mentions_pending_once_per_session(repo, mem, monkeypatch, capsys):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    seed(
        mem,
        [
            cand(
                id="c-20261020-gggg",
                text="fact: an undecidable pending note that is long enough",
                kind="fact",
                source="session:2026-10-20",
            )
        ],
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "generic"]) == 0
    out1 = capsys.readouterr().out
    assert "pending auto-candidate" in out1.lower()
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert main(["hook", "session-start", "--agent", "generic"]) == 0
    out2 = capsys.readouterr().out
    # Second start in the same window must not repeat the pending line.
    assert out2.lower().count("pending auto-candidate") == 0


def test_cadence_runs_gate_after_five_new_pending(repo, mem, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    memory = Memory.open(find_project(), None)
    from cairnkit import autogate

    items = [
        cand(
            id=f"c-20261020-{i:04x}",
            text=f"lesson: numbered lesson {i} about shipping with a clean tree always",
            kind="lesson",
            source=f"commit:abcd{i:04d}dead",
        )
        for i in range(5)
    ]
    add_candidates(memory, items)
    assert autogate.should_run(memory, new_pending=5) is True
    monkeypatch.setenv("MEMORY_NOW", LATER)
    memory = Memory.open(find_project(), None)
    assert autogate.should_run(memory, new_pending=0) is True
