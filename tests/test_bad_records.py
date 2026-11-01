"""A record that the code cannot use is skipped and counted at the read. Nothing else stops."""

from __future__ import annotations

import io
import json

import pytest
from conftest import make_fact, write_facts

from cairnkit.cli import main

GOOD = "f-20261001-0001"
BAD_RECORDS = [
    '{"type":"fact"}',
    '{"type":"tombstone"}',
    '{"type":"change"}',
    '{"type":"fact","id":"f-20260101-aaaa"}',
    '{"type":"fact","id":5,"text":"x"}',
    '{"type":"fact","id":["f"],"text":"x"}',
    '{"type":"fact","id":"f-20260101-aaaa","text":7}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","links":5}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","links":[5]}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","links":[{"rel":"related"}]}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","tags":5}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","expires_at":5,"scope":"short"}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","until_branch_merged":5,"scope":"short"}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","scope":[]}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","status":5}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","kind":{}}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","area":5}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","learned_at":5}',
    '{"type":"fact","id":"f-20260101-aaaa","text":"x","happened_at":5}',
    '{"type":"change","id":5}',
    '{"type":"change","id":"f-20261001-0001","add_links":5}',
    '{"type":"change","id":"f-20261001-0001","at":5,"status":[]}',
    '{"type":"nonsense"}',
    "{}",
    "[1,2]",
    "5",
    "null",
]
COMMANDS = [
    ["load"],
    ["check"],
    ["check", "--strict"],
    ["search", "billing"],
    ["tidy"],
    ["tidy", "--auto", "--dry-run"],
    ["show", GOOD],
    ["status"],
]


def _load(capsys):
    capsys.readouterr()
    assert main(["load"]) == 0
    return capsys.readouterr().out


def _append(mem, line):
    with (mem / "facts" / "main.jsonl").open("a") as fh:
        fh.write(line + "\n")


@pytest.mark.parametrize("line", BAD_RECORDS)
def test_one_bad_record_is_skipped_and_counted(mem, capsys, line):
    write_facts(mem, [make_fact(GOOD, "A true fact about billing.", pinned=True)])
    _append(mem, line)
    for command in COMMANDS:
        assert main(command) in (0, 1), command
    out = _load(capsys)
    assert "not loaded" not in out
    assert "A true fact about billing." in out
    assert "1 bad line(s) skipped" in out
    capsys.readouterr()
    assert main(["check"]) == 1
    assert "main.jsonl:2" in capsys.readouterr().out


def test_a_hook_runs_with_a_bad_record(mem, capsys, monkeypatch):
    write_facts(mem, [make_fact(GOOD, "A true fact about billing.", pinned=True)])
    _append(mem, '{"type":"fact"}')
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    assert "A true fact about billing." in capsys.readouterr().out


def test_a_fact_with_a_text_and_no_other_field_still_loads(mem, capsys):
    _append(mem, json.dumps({"type": "fact", "id": GOOD, "text": "A true old fact."}))
    for command in COMMANDS:
        assert main(command) in (0, 1), command
    assert "A true old fact." in _load(capsys)
