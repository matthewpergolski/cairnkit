"""What 0.3.1 left in a memory: facts its gate accepted end, and its files go."""

from __future__ import annotations

import json

from conftest import make_fact, write_facts

from cairnkit import legacy
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project

FRAGMENT = "// a comment fragment that a gate took from a commit diff"
GATE = {"basis": "guess", "kind": "lesson", "source": "commit:abc123def456"}


def _candidates(mem, *ids, text=FRAGMENT, **overrides):
    """The lines that 0.3.1 wrote: one candidate and one decision for each id."""
    folder = mem / "proposals"
    folder.mkdir(exist_ok=True)
    lines = []
    for fact_id in ids:
        candidate = {
            "type": "candidate",
            "id": f"c-{fact_id}",
            "text": text,
            "status": "pending",
            "origin": "draft",
            "area": "general",
            "basis": "guess",
            "kind": "lesson",
            "source": "commit:abc123def456",
        }
        decision = {
            "type": "decision",
            "id": f"c-{fact_id}",
            "status": "accepted",
            "fact_id": fact_id,
        }
        lines += [json.dumps({**candidate, **overrides}), json.dumps(decision)]
    (folder / "auto-candidates.jsonl").write_text("\n".join(lines) + "\n")


def _clean(mem):
    return legacy.clean(Memory.open(find_project(), None))


def test_a_mined_fact_ends_and_stays_in_the_archive(mem, capsys):
    write_facts(mem, [make_fact("f-20261001-0001", FRAGMENT, **GATE)])
    _candidates(mem, "f-20261001-0001")
    assert _clean(mem) == ["f-20261001-0001"]
    assert not (mem / "proposals" / "auto-candidates.jsonl").exists()
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "a comment fragment" not in capsys.readouterr().out
    assert main(["search", "comment", "--all"]) == 0
    assert "a comment fragment" in capsys.readouterr().out


def test_a_stated_or_pinned_fact_is_kept(mem):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", FRAGMENT, **{**GATE, "basis": "told"}),
            make_fact("f-20261001-0002", FRAGMENT + " two", **GATE, pinned=True),
        ],
    )
    _candidates(mem, "f-20261001-0001", "f-20261001-0002")
    assert _clean(mem) == []


def test_a_fact_that_a_person_accepted_with_another_basis_is_kept(mem):
    write_facts(mem, [make_fact("f-20261001-0001", FRAGMENT, **{**GATE, "basis": "seen"})])
    _candidates(mem, "f-20261001-0001")
    assert _clean(mem) == []


def test_a_candidate_that_failed_the_gate_was_chosen_by_someone(mem):
    short = "too short for the gate"
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", short, **GATE),
            make_fact("f-20261001-0002", FRAGMENT, **{**GATE, "kind": "fact"}),
        ],
    )
    _candidates(mem, "f-20261001-0001", text=short)
    assert _clean(mem) == []
    _candidates(mem, "f-20261001-0002", kind="fact")
    assert _clean(mem) == []


def test_a_fact_that_someone_changed_after_it_was_written_is_kept(mem):
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", FRAGMENT, **GATE, tags=["mine"]),
            make_fact("f-20261001-0002", FRAGMENT + " two", **GATE),
            make_fact("f-20261001-0003", FRAGMENT + " three", **{**GATE, "area": "api"}),
            {
                "type": "change",
                "id": "f-20261001-0002",
                "at": "2026-10-02T12:00:00+00:00",
                "reason": "Looked at it.",
                "writer": "main",
            },
        ],
    )
    _candidates(mem, "f-20261001-0001")
    assert _clean(mem) == []
    _candidates(mem, "f-20261001-0002", text=FRAGMENT + " two")
    assert _clean(mem) == []
    _candidates(mem, "f-20261001-0003", text=FRAGMENT + " three")
    assert _clean(mem) == []


def test_a_decision_with_no_candidate_line_proves_nothing(mem):
    write_facts(mem, [make_fact("f-20261001-0001", FRAGMENT, **GATE)])
    folder = mem / "proposals"
    folder.mkdir(exist_ok=True)
    line = {"type": "decision", "id": "c-1", "status": "accepted", "fact_id": "f-20261001-0001"}
    (folder / "auto-candidates.jsonl").write_text(json.dumps(line) + "\n")
    assert _clean(mem) == []
    assert not (folder / "auto-candidates.jsonl").exists()


def test_a_candidate_file_that_is_not_utf8_does_not_raise(mem):
    write_facts(mem, [make_fact("f-20261001-0001", FRAGMENT, **GATE)])
    _candidates(mem, "f-20261001-0001")
    path = mem / "proposals" / "auto-candidates.jsonl"
    path.write_bytes(b"\xff\xfe not text\n" + path.read_bytes())
    assert _clean(mem) == ["f-20261001-0001"]
    assert not path.exists()


def test_clean_is_safe_to_repeat_and_needs_no_file(mem):
    memory = Memory.open(find_project(), None)
    assert legacy.clean(memory) == []
    assert legacy.clean(memory) == []
