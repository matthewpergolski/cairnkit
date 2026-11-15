"""What a hook prints must reach the model whole.

Claude Code saves hook text over 10,000 characters to a file, and the model sees only the first
2,000 of it. In a real project the session start grew to 10,170 characters, and the agent saw the
preview only.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest
from conftest import make_fact, write_facts

from cairnkit import hookrun
from cairnkit.cli import main
from cairnkit.hookrun import HOOK_TEXT_LIMIT
from cairnkit.selection import FRAME_FOOTER

WORDS = "the deploy keeps its queue drained before a restart so that no job is lost on the way"


def run_hook(repo, event: str, **payload) -> str:
    argv = [sys.executable, "-m", "cairnkit", "hook", event, "--agent", "claude"]
    body = json.dumps({"session_id": "s1", "source": "startup", **payload})
    done = subprocess.run(argv, cwd=repo, input=body, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout


def fill(mem, facts: int, rules: int, status_lines: int, pinned: int = 0) -> None:
    records = [
        make_fact(f"f-20261003-{n:04x}", f"Pinned {n}: {WORDS}.", pinned=True)
        for n in range(pinned)
    ]
    records += [
        make_fact(f"f-20261001-{n:04x}", f"Fact {n}: {WORDS} {n}.", area=f"area{n % 9}")
        for n in range(facts)
    ]
    records += [
        make_fact(f"f-20261002-{n:04x}", f"Rule {n}: {WORDS}.", kind="rule", basis="told")
        for n in range(rules)
    ]
    write_facts(mem, records)
    (mem / "notes").mkdir(exist_ok=True)
    (mem / "notes" / "status.md").write_text(
        "".join(f"- Status line {n}: {WORDS} {WORDS}.\n" for n in range(status_lines))
    )


def frame_is_whole(text: str) -> bool:
    lines = text.splitlines()
    return FRAME_FOOTER in lines and any(line.startswith("Stored notes") for line in lines)


@pytest.mark.parametrize(
    ("facts", "rules", "status_lines", "pinned"),
    [(200, 4, 10, 0), (40, 30, 10, 0), (10, 60, 0, 0), (10, 4, 10, 120)],
)
def test_the_session_start_stays_under_the_hook_limit(
    repo, mem, facts, rules, status_lines, pinned
):
    fill(mem, facts, rules, status_lines, pinned)
    text = run_hook(repo, "session-start")
    assert len(text) <= HOOK_TEXT_LIMIT < 10_000
    assert frame_is_whole(text)
    assert "memory add" in text


def test_a_cut_load_says_so_outside_the_frame(repo, mem):
    fill(mem, 10, 4, 10, pinned=120)
    text = run_hook(repo, "session-start")
    head = text.split("Stored notes")[0]
    assert "`memory load`" in head


def test_a_small_load_is_not_cut(repo, mem):
    fill(mem, 5, 1, 2)
    text = run_hook(repo, "session-start")
    assert "Fact 4:" in text and "Status line 1:" in text
    assert "was cut" not in text


def test_a_subagent_load_stays_under_the_hook_limit(repo, mem):
    fill(mem, 40, 30, 10)
    out = run_hook(repo, "subagent-start", agent_id="a1", agent_type="general-purpose")
    text = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert len(out) <= HOOK_TEXT_LIMIT
    assert frame_is_whole(text)


def test_a_load_that_fills_its_room_prints_no_more_than_the_limit(mem, capsys, monkeypatch):
    """A cut can fit the room to the character. The line end that print adds counts too."""
    monkeypatch.setattr(hookrun, "fitted_load", lambda *args, **options: "x" * args[3])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    assert len(capsys.readouterr().out) <= HOOK_TEXT_LIMIT
