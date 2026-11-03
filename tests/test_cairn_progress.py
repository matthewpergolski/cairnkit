"""Cairn animation gates and stone stacking for memory update (TTY vs plain)."""

from __future__ import annotations

import inspect
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


def test_want_anim_false_with_github_actions():
    """GITHUB_ACTIONS alone turns the cairn off, same as CI."""
    assert want_anim(Terminal(), env={"TERM": "xterm", "GITHUB_ACTIONS": "true"}) is False


def test_want_anim_false_with_no_color():
    assert want_anim(Terminal(), env={"TERM": "xterm", "NO_COLOR": "1"}) is False


def test_want_anim_true_when_no_color_is_empty():
    """Empty NO_COLOR is unset for this gate (same as missing)."""
    assert want_anim(Terminal(), env={"TERM": "xterm", "NO_COLOR": ""}) is True


def test_want_anim_false_with_cairnkit_plain():
    assert want_anim(Terminal(), env={"TERM": "xterm", "CAIRNKIT_PLAIN": "1"}) is False


def test_want_anim_false_with_memory_plain():
    assert want_anim(Terminal(), env={"TERM": "xterm", "MEMORY_PLAIN": "1"}) is False


def test_want_anim_has_no_opt_out_parameter():
    """Plain force goes through Progress(anim=False), not a second want_anim knob."""
    assert "opt_out" not in inspect.signature(want_anim).parameters


def test_want_anim_true_on_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("CAIRNKIT_PLAIN", raising=False)
    monkeypatch.delenv("MEMORY_PLAIN", raising=False)
    assert want_anim(Terminal(), env={"TERM": "xterm-256color"}) is True


def test_build_stage_does_not_add_a_stone():
    assert any(s.name == "Build" and not s.stone for s in STAGES)
    stone_names = [s.name for s in STAGES if s.stone]
    assert stone_names == ["Check", "Fetch", "Install", "Verify"]


def test_build_and_unknown_labels_do_not_increment_stacked():
    bar = Progress(io.StringIO(), anim=False)
    bar.start("Mystery")
    bar.done()
    assert bar.stacked == 0
    bar.start("Build")
    bar.done()
    assert bar.stacked == 0
    bar.start("Check")
    bar.done()
    assert bar.stacked == 1


def test_default_drip_delay_matches_settled_pause():
    assert Progress(anim=False).drip_delay == 0.12


def test_start_stops_the_previous_ticker(monkeypatch):
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    out = Terminal()
    bar = Progress(out, anim=True, drip_delay=0)
    bar.start("Check")
    first = bar.ticker
    assert first is not None
    bar.start("Fetch")
    assert not first.is_alive()
    assert bar.ticker is not None and bar.ticker.is_alive()
    assert bar.label == "Fetch"
    bar.done()
    bar.close()


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
    assert "●" not in text


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
    assert bar.stacked == 4
    bar.finish("memory updated: 0.3.0 → 0.3.1.")
    text = out.getvalue()
    assert "● ● ● ●" in text
    assert "0.3.0" in text and "0.3.1" in text
    assert "→" in text


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
