"""A repo doc that teaches an older memory hears, once, which one wins. No tracked file changes."""

from __future__ import annotations

import io
import json

import pytest
from conftest import git

from cairnkit.cli import main

OLD = "# Rules\nRead memory-bank/status.md first.\nRun tools/check_memory.py at session end.\n"


def _start(capsys, monkeypatch) -> str:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    return capsys.readouterr().out


def test_a_session_start_names_the_lines_once_and_says_which_wins(mem, repo, capsys, monkeypatch):
    (repo / "CLAUDE.md").write_text(OLD)
    first = _start(capsys, monkeypatch)
    assert "CLAUDE.md:2" in first and "CLAUDE.md:3" in first
    assert "`memory load` and `memory instructions` win" in first
    assert "The rest of that file still stands" in first
    assert "CLAUDE.md:2" not in _start(capsys, monkeypatch)
    assert git(repo, "status", "--short", "--", "CLAUDE.md") == "?? CLAUDE.md\n"
    assert (repo / "CLAUDE.md").read_text() == OLD


def test_a_new_old_line_is_named_once_more(mem, repo, capsys, monkeypatch):
    (repo / "CLAUDE.md").write_text(OLD)
    _start(capsys, monkeypatch)
    (repo / "AGENTS.md").write_text("Read memory-bank/log.md.\n")
    second = _start(capsys, monkeypatch)
    assert "AGENTS.md:1" in second and "CLAUDE.md:2" not in second


@pytest.mark.parametrize(
    "text",
    [
        "Read memory-bank/notes/status.md first.\n",
        "Run `memory load`. Never commit memory-bank.\n",
        "Read docs/status.md first.\n",
    ],
)
def test_a_doc_of_the_current_layout_hears_nothing(mem, repo, capsys, monkeypatch, text):
    (repo / "CLAUDE.md").write_text(text)
    assert "teaches an older memory" not in _start(capsys, monkeypatch)


def test_an_open_migration_says_it_already_and_this_line_waits(mem, repo, capsys, monkeypatch):
    (repo / "CLAUDE.md").write_text(OLD)
    proposals = mem / "proposals"
    proposals.mkdir(exist_ok=True)
    (proposals / "migrate-followups.md").write_text(
        "# Migration follow-up (pending): 1 item(s)\n\n1. `CLAUDE.md:2` (old path)\n"
    )
    assert "teaches an older memory" not in _start(capsys, monkeypatch)
    (proposals / "migrate-followups.md").unlink()
    assert "teaches an older memory" in _start(capsys, monkeypatch)


def test_a_load_with_no_session_stays_silent_and_writes_nothing(mem, repo, capsys):
    (repo / "CLAUDE.md").write_text(OLD)
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "teaches an older memory" not in capsys.readouterr().out
