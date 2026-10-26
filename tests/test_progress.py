"""The step display of `memory update`: a bar on a terminal, plain lines when piped."""

from __future__ import annotations

import io
import re

from cairnkit.progress import Progress


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_piped_output_is_one_plain_line_per_step():
    out = io.StringIO()
    bar = Progress(out)
    bar.say("Source: /src (folder)")
    bar.start("Check")
    bar.done()
    bar.start("Build")
    bar.fail()
    bar.close()
    assert out.getvalue() == "Source: /src (folder)\n  Check... done\n  Build... failed\n"


def test_piped_summary_is_a_plain_line():
    out = io.StringIO()
    bar = Progress(out)
    bar.start("Install")
    bar.done()
    bar.finish("memory updated: 0.1.0 -> 0.2.0.")
    assert out.getvalue().endswith("  Install... done\nmemory updated: 0.1.0 -> 0.2.0.\n")


def test_terminal_shows_a_bar_and_the_summary(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")
    out = Terminal()
    bar = Progress(out)
    for step in ("Check", "Fetch", "Build"):
        bar.start(step)
        bar.done()
    bar.finish("Updated to 0.2.0")
    text = out.getvalue()
    assert "━" in text
    assert "◇ Updated to 0.2.0" in text
    assert "\x1b[38;5;" in text  # color on a terminal
    assert text.rindex("\x1b[?25h") > text.rindex("\x1b[?25l")


def test_no_color_keeps_the_bar_and_drops_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    out = Terminal()
    bar = Progress(out)
    bar.start("Build")
    bar.fail()
    bar.close()
    text = out.getvalue()
    assert "✖ Build" in text
    assert not re.search(r"\x1b\[[0-9;]*m", text)


def test_dumb_terminal_gets_plain_lines(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    out = Terminal()
    bar = Progress(out)
    bar.start("Check")
    bar.done()
    assert out.getvalue() == "  Check... done\n"


def test_cursor_comes_back_after_a_failure(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    out = Terminal()
    bar = Progress(out)
    bar.start("Install")
    bar.close()  # an exception path: close without done or fail
    text = out.getvalue()
    assert "\x1b[?25l" in text
    assert text.rindex("\x1b[?25h") > text.rindex("\x1b[?25l")
