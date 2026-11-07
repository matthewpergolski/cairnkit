"""A session-start load cut to fit the hook limit drops long-term facts first, live work last."""

from __future__ import annotations

import pytest
from conftest import add_worktree
from test_hook_size import fill, run_hook

from cairnkit.hookrun import CUT_NOTE, HOOK_TEXT_LIMIT
from cairnkit.load import NOTE_LINES


@pytest.mark.parametrize("source", ["startup", "resume", "compact", "clear"])
def test_a_cut_load_keeps_live_work_and_drops_long_term_first(repo, mem, source):
    fill(mem, 200, 4, 10, pinned=40)
    other = add_worktree(repo, "wip-parser")
    (other / "parser_notes.txt").write_text("notes\n")
    text = run_hook(repo, "session-start", source=source)
    assert CUT_NOTE in text and len(text) <= HOOK_TEXT_LIMIT
    lines = text.splitlines()
    live = next(n for n, line in enumerate(lines) if line.startswith("- [live]"))
    assert "wip-parser" in lines[live] and lines[live - 1] == "## Live work"
    status = [line for line in lines if line.startswith("- [status]")]
    long_term = [line for line in lines if line.startswith("- [f-20261001-")]
    assert status, "the status note outranks long-term facts"
    assert len(status) == NOTE_LINES or not long_term, "a status line went before a long-term fact"
