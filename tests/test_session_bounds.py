"""The state of one session stays small and holds the newest, in a session that runs for days.

In a real project one session ran from Nov 1 to Nov 3. Its state held 41 failed commands
(24 KB) and 200 file names, many of them bold words from a helper's report such as `**Answers.**`.
Each hook reads and writes that file.
"""

from __future__ import annotations

import pytest
from test_stop_replay import Session

from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.session import load_state
from cairnkit.signals import FAILS_LIMIT, NAMED_LIMIT


@pytest.fixture
def session(repo, mem, capsys, monkeypatch):
    made = Session("claude", repo, capsys, monkeypatch)
    made.begin()
    return made


def state() -> dict:
    return load_state(Memory.open(find_project()), "s1") or {}


def test_text_that_is_not_the_owner_names_no_files(session):
    report = "<task-notification>\n**Answers.** The helper changed answers.py and docs/a.md.\n"
    session.hook("prompt", prompt=report)
    assert state().get("named", []) == []
    session.hook("prompt", prompt="Please keep config/settings.py as it is.")
    assert state()["named"] == ["config/settings.py"]


def test_bold_marks_are_no_part_of_a_name(session):
    session.hook("prompt", prompt="Look at **notes/plan.md** first.")
    assert state()["named"] == ["notes/plan.md"]


def test_a_full_list_of_names_keeps_the_newest(session):
    for n in range(NAMED_LIMIT + 5):
        session.hook("prompt", prompt=f"Check file{n:04d}.py now.")
    named = state()["named"]
    assert len(named) == NAMED_LIMIT
    assert f"file{NAMED_LIMIT + 4:04d}.py" in named
    assert "file0000.py" not in named


def test_old_failures_leave_and_cannot_pair_with_a_later_pass(session):
    session.tool("sh report.sh", False)
    for n in range(FAILS_LIMIT):
        session.tool(f"sh other{n}.sh", False)
    assert len(state()["fails"]) == FAILS_LIMIT
    assert "sh report.sh" not in state()["fails"]
    session.tool("REPORT_LOCALE=C sh report.sh", True)
    assert "What fixed it?" not in (session.stop_text(session.hook("stop")) or "")


def test_a_failure_again_counts_as_new(session):
    session.tool("sh report.sh", False)
    for n in range(FAILS_LIMIT - 1):
        session.tool(f"sh other{n}.sh", False)
    session.tool("sh report.sh", False)
    session.tool("sh last.sh", False)
    assert state()["fails"].get("sh report.sh") == 2
