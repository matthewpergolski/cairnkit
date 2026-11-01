"""A session start spends words on facts. Each other line must give an action or knowledge."""

from __future__ import annotations

import io
import json

import pytest

from cairnkit.cli import main
from cairnkit.discover import DISCOVER, RULES_SHORT

AGENTS = ("claude", "codex", "cursor", "pi", "opencode", "grok")
OTHER_WORDS_BUDGET = 104


def hook(capsys, monkeypatch, event, agent, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    capsys.readouterr()
    assert main(["hook", event, "--agent", agent]) == 0
    return capsys.readouterr().out


def model_text(capsys, monkeypatch, agent) -> str:
    """What the model reads, in the form that this tool reads."""
    payload = {"session_id": f"s-{agent}", "source": "startup"}
    out = hook(capsys, monkeypatch, "session-start", agent, payload)
    if agent == "cursor":
        return json.loads(out)["additional_context"]
    if agent == "grok":
        event = {**payload, "hook_event_name": "PostToolUse"}
        held = hook(capsys, monkeypatch, "after-shell", agent, event)
        return json.loads(held)["hookSpecificOutput"]["additionalContext"]
    return out


@pytest.fixture
def thirty_facts(mem):
    assert main(["hooks", "install"]) == 0
    for index in range(30):
        assert (
            main(
                [
                    "add",
                    f"The export job {index} writes to the replica, because reads run long.",
                    "--area",
                    f"area{index % 6}",
                    "--basis",
                    "seen",
                    "--source",
                    "session:2026-10-30",
                ]
            )
            == 0
        )
    return mem


@pytest.mark.parametrize("agent", AGENTS)
def test_no_lookup_text_repeats_in_a_session_start(thirty_facts, capsys, monkeypatch, agent):
    text = model_text(capsys, monkeypatch, agent)
    assert text.count("Look up:") == 1
    assert text.count("memory show ID") == 1
    assert text.count("Stored notes") == 1


@pytest.mark.parametrize("agent", AGENTS)
def test_words_that_are_not_facts_stay_small(thirty_facts, capsys, monkeypatch, agent):
    text = model_text(capsys, monkeypatch, agent)
    other = [line for line in text.splitlines() if not line.startswith("- [f-")]
    assert len(text.splitlines()) > len(other) >= 1
    assert sum(len(line.split()) for line in other) <= OTHER_WORDS_BUDGET


def test_the_rules_hold_no_copy_of_the_lookup_line():
    assert DISCOVER not in RULES_SHORT


def test_a_plain_load_keeps_the_lookup_line(thirty_facts, capsys):
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert out.count("Look up:") == 1
    assert out.count("memory show ID") == 1
