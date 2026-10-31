"""Cairn animation gates and stone stacking for memory update (TTY vs plain)."""

from __future__ import annotations

import io
import re

from cairnkit.progress import STAGES, Progress, want_anim


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_want_anim_false_when_not_tty():
    assert want_anim(io.StringIO(), env={"TERM": "xterm"}) is False


def test_want_anim_false_in_ci(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert want_anim(Terminal(), env={"TERM": "xterm", "CI": "true"}) is False


def test_want_anim_false_with_no_color():
    assert want_anim(Terminal(), env={"TERM": "xterm", "NO_COLOR": "1"}) is False


def test_want_anim_false_with_cairnkit_plain():
    assert want_anim(Terminal(), env={"TERM": "xterm", "CAIRNKIT_PLAIN": "1"}) is False


def test_want_anim_false_with_memory_plain():
    assert want_anim(Terminal(), env={"TERM": "xterm", "MEMORY_PLAIN": "1"}) is False


def test_want_anim_false_when_opt_out():
    assert want_anim(Terminal(), env={"TERM": "xterm"}, opt_out=True) is False


def test_want_anim_true_on_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("CAIRNKIT_PLAIN", raising=False)
    monkeypatch.delenv("MEMORY_PLAIN", raising=False)
    assert want_anim(Terminal(), env={"TERM": "xterm-256color"}) is True


def test_build_stage_does_not_add_a_stone():
    assert any(s.name == "Build" and not s.stone for s in STAGES)
    stone_names = [s.name for s in STAGES if s.stone]
    assert stone_names == ["Check", "Fetch", "Install", "Verify"]


def test_piped_output_stays_plain_step_lines():
    out = io.StringIO()
    bar = Progress(out, anim=False)
    bar.start("Check")
    bar.done()
    bar.start("Build")
    bar.done()
    bar.finish("memory updated: 0.1.0 -> 0.2.0.")
    text = out.getvalue()
    assert "  Check... done\n" in text
    assert "  Build... done\n" in text
    assert text.endswith("memory updated: 0.1.0 -> 0.2.0.\n")
    assert "●" not in text and "○" not in text


def test_opt_out_forces_plain_on_tty(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    out = Terminal()
    bar = Progress(out, anim=False)
    bar.start("Check")
    bar.done()
    assert out.getvalue() == "  Check... done\n"


def test_tty_stacks_four_stones_then_flag(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    out = Terminal()
    bar = Progress(out, anim=True, drip_delay=0)
    for name in ("Check", "Fetch", "Build", "Install", "Verify"):
        bar.start(name)
        bar.done()
    bar.finish("memory updated: 0.3.0 → 0.3.1.")
    text = out.getvalue()
    # Four product stones; Build is silent on the cairn.
    assert text.count("●") + text.count("○") >= 4
    assert "0.3.0" in text and "0.3.1" in text
    assert "→" in text or "->" in text


def test_tty_failure_stays_plain(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    out = Terminal()
    bar = Progress(out, anim=True, drip_delay=0)
    bar.start("Install")
    bar.fail()
    bar.close()
    text = out.getvalue()
    assert "  Install... failed\n" in text or text.rstrip().endswith("Install... failed")
    assert "✖" not in text
    assert "→" not in text


def test_drip_prints_changelog_lines(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    out = Terminal()
    bar = Progress(out, anim=True, drip_delay=0)
    bar.drip(["### Added", "- a fix"])
    text = out.getvalue()
    assert "### Added" in text
    assert "- a fix" in text


def test_no_color_uses_plain_not_bar(monkeypatch):
    """NO_COLOR turns animation off entirely (stricter than 0.3.1 bar-without-color)."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "xterm-256color")
    out = Terminal()
    bar = Progress(out)  # gate from env
    bar.start("Build")
    bar.fail()
    bar.close()
    text = out.getvalue()
    assert "Build... failed" in text or re.search(r"Build.*failed", text)
    assert "━" not in text
