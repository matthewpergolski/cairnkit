"""Three identical failures make stop name stop, memory check, and ask.

Docs name the adapters that cannot see a command failure.
"""

from __future__ import annotations

import io
from pathlib import Path

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project

ROOT = Path(__file__).resolve().parents[1]


def test_stop_after_three_failures_says_stop_check_and_ask(repo, mem, monkeypatch, capsys):
    from cairnkit.session import note_failure

    memory = Memory.open(find_project(), None)
    for _ in range(3):
        note_failure(memory, "s1", "pytest -q")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    capsys.readouterr()
    main(["hook", "stop", "--agent", "generic"])
    err = capsys.readouterr().err.lower()
    assert "stop" in err
    assert "memory check" in err
    assert "ask" in err


def test_docs_name_adapters_that_cannot_observe_command_failures():
    text = (ROOT / "docs" / "FORMAT.md").read_text()
    lowered = text.lower()
    assert "aftershellexecution" in lowered.replace(" ", "").replace("_", "")
    assert "posttooluse" in lowered.replace(" ", "").replace("_", "")
    for name in ("opencode", "pi", "grok"):
        assert name in lowered
    assert "generic" in lowered
    assert "cannot" in lowered or "no hook" in lowered or "gap" in lowered
