"""What 0.3.1 left in a memory: mined facts end, and its files go."""

from __future__ import annotations

import json

from conftest import make_fact, write_facts

from cairnkit import legacy
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project


def _mined(mem, *ids):
    folder = mem / "proposals"
    folder.mkdir(exist_ok=True)
    lines = [json.dumps({"type": "decision", "id": f"c-{i}", "fact_id": i}) for i in ids]
    (folder / "auto-candidates.jsonl").write_text("\n".join(lines) + "\n")


def test_a_mined_fact_ends_and_stays_in_the_archive(mem, capsys):
    write_facts(mem, [make_fact("f-20261001-0001", "// a comment fragment", basis="guess")])
    _mined(mem, "f-20261001-0001")
    memory = Memory.open(find_project(), None)
    assert legacy.clean(memory) == ["f-20261001-0001"]
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
            make_fact("f-20261001-0001", "Stated.", basis="told"),
            make_fact("f-20261001-0002", "Pinned.", basis="guess", pinned=True),
        ],
    )
    _mined(mem, "f-20261001-0001", "f-20261001-0002")
    assert legacy.clean(Memory.open(find_project(), None)) == []


def test_clean_is_safe_to_repeat_and_needs_no_file(mem):
    memory = Memory.open(find_project(), None)
    assert legacy.clean(memory) == []
    assert legacy.clean(memory) == []
