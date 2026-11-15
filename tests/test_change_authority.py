"""`memory change --status superseded --superseded-by NEW` keeps the force of a person's word.

An agent's claim that the owner's words did not confirm, or a fact with less authority, must not
end a fact that the owner stated. `memory add --supersedes` already keeps such a fact. Both say
how to confirm: quote the owner's words in this turn, or the owner runs the command.
"""

from __future__ import annotations

import re

from test_told_claims import facts, prompt, transcripts  # noqa: F401

from cairnkit.cli import main

HOW = "quote the owner's words in this turn, or the owner runs"


def add(capsys, monkeypatch, *args: str, agent: bool = False) -> tuple[str, str]:
    if agent:
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s")
    capsys.readouterr()
    assert main(["add", *args, "--area", "x"]) == 0
    out = capsys.readouterr().out
    for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)
    return re.search(r"added (f-\S+)", out).group(1), out


def change(capsys, monkeypatch, old: str, new: str, agent: bool = True) -> tuple[int, str]:
    if agent:
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s")
    capsys.readouterr()
    code = main(["change", old, "--status", "superseded", "--superseded-by", new, "--reason", "r"])
    captured = capsys.readouterr()
    for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)
    return code, captured.out + captured.err


def status(mem, fid: str) -> str:
    return [r for r in facts(mem) if r.get("id") == fid and r.get("status")][-1]["status"]


def owner_rule(capsys, monkeypatch) -> str:
    return add(
        capsys, monkeypatch, "Never force-push to main.", "--kind", "rule", "--basis", "told"
    )[0]


def test_an_unconfirmed_claim_cannot_replace_the_owner_rule(mem, capsys, monkeypatch):
    old = owner_rule(capsys, monkeypatch)
    new, out = add(
        capsys,
        monkeypatch,
        "Force-push to main is fine.",
        "--kind",
        "rule",
        "--basis",
        "told",
        agent=True,
    )
    assert "told: not confirmed" in out
    code, out = change(capsys, monkeypatch, old, new)
    assert code != 0 and HOW in out
    assert status(mem, old) == "active"


def test_a_seen_fact_cannot_replace_the_owner_rule(mem, capsys, monkeypatch):
    old = owner_rule(capsys, monkeypatch)
    new, _ = add(capsys, monkeypatch, "Force-push is used.", "--basis", "seen", agent=True)
    code, out = change(capsys, monkeypatch, old, new)
    assert code != 0 and HOW in out
    assert status(mem, old) == "active"


def test_a_confirmed_claim_replaces_the_owner_rule(mem, capsys, monkeypatch):
    old = owner_rule(capsys, monkeypatch)
    prompt(capsys, monkeypatch, "From now on, never force-push to any branch.")
    new, out = add(
        capsys,
        monkeypatch,
        "Never force-push to any branch.",
        "--kind",
        "rule",
        "--basis",
        "told",
        agent=True,
    )
    assert "told: confirmed" in out
    code, _ = change(capsys, monkeypatch, old, new)
    assert code == 0 and status(mem, old) == "superseded"


def test_the_owner_may_replace_their_rule_with_any_fact(mem, capsys, monkeypatch):
    old = owner_rule(capsys, monkeypatch)
    new, _ = add(capsys, monkeypatch, "Force-push is used.", "--basis", "seen", agent=True)
    code, _ = change(capsys, monkeypatch, old, new, agent=False)
    assert code == 0 and status(mem, old) == "superseded"


def test_an_agent_fact_can_replace_an_agent_fact(mem, capsys, monkeypatch):
    old, _ = add(capsys, monkeypatch, "The queue drops jobs.", "--basis", "seen", agent=True)
    new, _ = add(capsys, monkeypatch, "The queue keeps jobs.", "--basis", "seen", agent=True)
    code, _ = change(capsys, monkeypatch, old, new)
    assert code == 0 and status(mem, old) == "superseded"


def test_add_supersedes_says_how_to_confirm(mem, capsys, monkeypatch):
    old = owner_rule(capsys, monkeypatch)
    _, out = add(
        capsys,
        monkeypatch,
        "Force-push to main is fine.",
        "--kind",
        "rule",
        "--basis",
        "told",
        "--supersedes",
        old,
        agent=True,
    )
    assert "not superseded" in out and HOW in out
    assert status(mem, old) == "active"
