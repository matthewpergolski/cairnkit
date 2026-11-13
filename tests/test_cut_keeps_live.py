"""A session-start load cut to fit the hook limit drops long-term facts first, live work last."""

from __future__ import annotations

import pytest
from conftest import add_worktree
from test_hook_size import fill, run_hook

from cairnkit.hookrun import CUT_NOTE, HOOK_TEXT_LIMIT, _cut
from cairnkit.live import ORDER
from cairnkit.load import NOTE_WORDS, note_head
from cairnkit.selection import FRAME_FOOTER, FRAME_HEADER


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
    assert ORDER in lines, "the live work stays, so its order stays"
    status = [line for line in lines if line.startswith("- [status]")]
    long_term = [line for line in lines if line.startswith("- [f-20261001-")]
    assert status, "the status note outranks long-term facts"
    whole = note_head(mem / "notes" / "status.md", words=NOTE_WORDS)
    assert len(status) == len(whole) or not long_term, "a status line went before a long-term fact"


def test_a_cut_of_all_live_work_drops_the_order_that_points_to_it():
    bullet = "- [live] " + "x" * 300
    lines = [
        "# Project memory (/m)",
        "## Advisory rules",
        "- [f-20261001-0001] Keep it short.",
        ORDER,
        FRAME_HEADER,
        "## Live work",
        bullet,
        FRAME_FOOTER,
        "1 fact(s) shown.",
    ]
    text = "\n".join(lines)
    room = len(text) - len(bullet) + len(CUT_NOTE) - 5
    out = _cut(text, room)
    assert "## Live work" not in out and bullet not in out
    assert ORDER not in out, "the order points to a list that is gone"
    assert "Keep it short." in out and FRAME_FOOTER in out
