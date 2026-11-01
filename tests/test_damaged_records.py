"""Damage to one line loses that line only. Nothing crashes, and the count is true."""

from __future__ import annotations

import json

import pytest
from conftest import make_fact, read_jsonl, write_facts

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.store import fact_files, read_records

RULE = "f-20261001-0001"
TRAP = "f-20261001-0002"
EMOJI = "f-20261001-0003"


def _torn_inside_an_emoji(mem):
    write_facts(
        mem,
        [
            make_fact(RULE, "Always rebase before a merge.", kind="rule"),
            make_fact(TRAP, "Billing webhook retries forever.", kind="trap", pinned=True),
        ],
    )
    path = mem / "facts" / "main.jsonl"
    whole = json.dumps(make_fact(EMOJI, "Sessions end with 🎉 here."), ensure_ascii=False)
    with path.open("ab") as fh:
        fh.write(whole.encode()[: whole.encode().index("🎉".encode()) + 2])
    return path


def _load(capsys):
    capsys.readouterr()
    assert main(["load"]) == 0
    return capsys.readouterr().out


def _add(text):
    return main(["add", text, "--basis", "seen", "--source", "session:2026-11-01"])


def test_a_cut_inside_an_emoji_loses_only_that_line(mem, capsys):
    _torn_inside_an_emoji(mem)
    out = _load(capsys)
    assert "1 bad line(s) skipped" in out
    assert "Always rebase" in out
    assert "Billing webhook" in out
    assert "2 fact(s) shown" in out


def test_an_add_after_a_torn_tail_lands_on_a_new_line_and_loads(mem, capsys):
    path = _torn_inside_an_emoji(mem)
    before = path.read_bytes()
    assert _add("A new fact after the crash.") == 0
    assert path.read_bytes().startswith(before + b"\n")
    assert "A new fact after the crash." in _load(capsys)


def test_a_bad_byte_in_the_middle_of_a_file_loses_only_that_line(mem, capsys):
    path = mem / "facts" / "main.jsonl"
    good = json.dumps(make_fact(RULE, "Before the bad byte.", pinned=True)).encode()
    bad = json.dumps(make_fact(TRAP, "Holds a bad byte XX.")).encode().replace(b"XX", b"\xe9")
    after = json.dumps(make_fact(EMOJI, "After the bad byte.", pinned=True)).encode()
    path.write_bytes(good + b"\n" + bad + b"\n" + after + b"\n")
    records, errors = read_records(fact_files(mem))
    assert [r["id"] for r in records] == [RULE, EMOJI]
    assert len(errors) == 1
    assert "main.jsonl:2" in errors[0]


def test_purge_works_on_a_file_with_a_bad_line(mem, capsys):
    path = _torn_inside_an_emoji(mem)
    assert main(["purge", RULE, "--reason", "Testing.", "--yes"]) == 0
    assert "Always rebase" not in path.read_bytes().decode(errors="replace")
    assert b"\xf0\x9f" in path.read_bytes(), "the rewrite keeps the other bytes as they were"
    assert main(["purge", "f-20991231-ffff", "--reason", "x", "--yes"]) == 1


def test_purge_removes_a_torn_line_by_its_id(mem, capsys):
    path = _torn_inside_an_emoji(mem)
    assert main(["purge", EMOJI, "--reason", "Testing.", "--yes"]) == 0
    assert read_records([path])[1] == []


@pytest.mark.parametrize(
    "command",
    [["check"], ["search", "billing"], ["tidy"], ["tidy", "--auto", "--dry-run"], ["status"]],
)
def test_no_command_crashes_on_a_torn_line(mem, command):
    _torn_inside_an_emoji(mem)
    assert main(command) in (0, 1)


def test_earlier_bytes_do_not_change_on_an_add(mem):
    path = _torn_inside_an_emoji(mem)
    before = path.read_bytes()
    assert _add("Another fact.") == 0
    assert path.read_bytes()[: len(before)] == before


def test_a_line_separator_inside_a_text_does_not_split_a_record(mem):
    text = "One fact with a" + chr(0x2028) + "line separator."
    path = mem / "facts" / "main.jsonl"
    path.write_text(json.dumps(make_fact(RULE, text), ensure_ascii=False) + "\n", encoding="utf-8")
    records, errors = read_records([path])
    assert errors == []
    assert records[0]["text"] == text


def test_a_clean_file_reads_as_before(mem):
    write_facts(mem, [make_fact(RULE, "One."), make_fact(TRAP, "Two.")])
    memory = Memory.open(find_project(), None)
    assert memory.errors == []
    assert set(memory.states) == {RULE, TRAP}
    assert [r["id"] for r in read_jsonl(mem / "facts" / "main.jsonl")] == [RULE, TRAP]
