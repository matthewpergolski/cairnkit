"""Defects that an independent review found in the fitted load, the pairing and the temp files."""

from __future__ import annotations

import json
import os
import time

import pytest
from conftest import make_fact, write_facts
from test_stop_replay import Session

from cairnkit import hookrun
from cairnkit.hookrun import _cut
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.selection import FRAME_FOOTER, FRAME_HEADER
from cairnkit.session import load_state

WORDS = "the deploy keeps its queue drained before a restart so that no job is lost on the way"


def too_big(mem, pinned: int = 150) -> None:
    write_facts(
        mem,
        [
            make_fact(f"f-20261003-{n:04x}", f"Pinned {n}: {WORDS}.", pinned=True)
            for n in range(pinned)
        ],
    )


def session_text() -> str:
    return hookrun._session_text(find_project(), None, "s1")


def test_a_rule_notice_survives_a_load_that_is_too_big(repo, mem):
    """Each pass of the fitted load took the one-time notices, and the last pass had none."""
    too_big(mem)
    write_facts(mem, [make_fact("f-20261004-0002", "An old rule, now ended.", status="expired")])
    record = {"id": "f-20261004-0002", "by": "agent:claude", "what": "ended"}
    (mem / ".rule-notices").write_text(json.dumps(record) + "\n")
    text = session_text()
    assert len(text) <= hookrun.HOOK_TEXT_LIMIT
    assert "f-20261004-0002" in text.split(FRAME_HEADER)[0]


def test_a_load_that_never_fits_stops_after_a_few_passes(repo, mem, monkeypatch):
    too_big(mem, 400)
    calls = []
    real = hookrun.run_load

    def counted(*args, **kwargs):
        calls.append(args[3])
        return real(*args, **kwargs)

    monkeypatch.setattr(hookrun, "run_load", counted)
    text = session_text()
    assert len(calls) <= hookrun.MAX_LOAD_PASSES
    assert len(text) <= hookrun.HOOK_TEXT_LIMIT


def framed(rules: int, stored: int, tail: int) -> str:
    return "\n".join(
        [
            "# Project memory (x)",
            "memory check: 1 to do",
            "## Advisory rules",
            *[f"- [f-r{n}] Rule {n}: {WORDS}." for n in range(rules)],
            FRAME_HEADER,
            *[f"- [f-s{n}] Stored {n}: {WORDS}." for n in range(stored)],
            FRAME_FOOTER,
            *[f"tail line {n}: {WORDS}" for n in range(tail)],
        ]
    )


def test_a_cut_keeps_the_rules_and_the_frame_and_fits_with_a_long_tail():
    text = _cut(framed(rules=3, stored=40, tail=40), 2_000)
    assert len(text) <= 2_000
    assert text.count("Rule ") == 3
    assert FRAME_HEADER in text and FRAME_FOOTER in text
    assert text.index(FRAME_HEADER) < text.index(FRAME_FOOTER)


@pytest.fixture
def session(repo, mem, capsys, monkeypatch):
    made = Session("claude", repo, capsys, monkeypatch)
    made.begin()
    return made


def test_a_shared_plain_step_is_no_fix(session):
    session.tool("pytest -x && ls", False)
    session.tool("FOO=1 ls", True)
    assert session.stop_text(session.hook("stop")) is None


def test_the_failed_step_before_a_status_echo_is_still_a_fix(session):
    session.tool('sh report.sh; echo "exit=$?"', False)
    session.tool("REPORT_LOCALE=C sh report.sh", True)
    assert "What fixed it?" in session.stop_text(session.hook("stop"))


def test_an_owner_prompt_that_names_memory_check_still_counts(session):
    session.hook("prompt", prompt="Run memory check and keep config/settings.py as it is.")
    state = load_state(Memory.open(find_project()), "s1") or {}
    assert "config/settings.py" in state.get("named", [])


def test_old_temp_files_of_killed_hooks_go(session, mem):
    folder = mem / ".sessions"
    old = folder / ".state-killed.tmp"
    old.write_text("{}")
    then = time.time() - 3 * 3600
    os.utime(old, (then, then))
    session.hook("prompt", prompt="Keep config/settings.py.")
    assert not old.exists()
