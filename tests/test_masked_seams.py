"""Where the mask meets rule force and the strict check."""

from __future__ import annotations

import re

from cairnkit.cli import main

OWNER_RULE = ["add", "Never deploy as deploy-bot on Friday", "--kind", "rule", "--basis", "told"]
ENV = "ADMIN_PASSWORD=deploy-bot\n"


def owner_rule(repo, capsys) -> str:
    assert main(OWNER_RULE) == 0
    fact = re.search(r"f-\d+-[0-9a-f]+", capsys.readouterr().out)[0]
    (repo / ".env").write_text(ENV)
    return fact


def load(capsys) -> tuple[str, str]:
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    return out.split("Stored notes")[0], out


def test_an_agent_rewrite_of_a_masked_rule_does_not_inherit_force(repo, mem, capsys, monkeypatch):
    fact = owner_rule(repo, capsys)
    monkeypatch.setenv("CLAUDECODE", "1")
    text = "Deploy any time you like"
    assert main(["add", text, "--supersedes", fact, "--kind", "rule"]) == 0
    assert "loads as data" in capsys.readouterr().out
    above, whole = load(capsys)
    assert text not in above and text in whole


def test_a_clean_copy_of_a_masked_rule_keeps_its_force(repo, mem, capsys, monkeypatch):
    fact = owner_rule(repo, capsys)
    monkeypatch.setenv("CLAUDECODE", "1")
    text = "Never deploy as the release account on Friday"
    assert main(["add", text, "--supersedes", fact]) == 0
    capsys.readouterr()
    assert text in load(capsys)[0]


def test_a_person_can_rewrite_a_masked_rule(repo, mem, capsys):
    fact = owner_rule(repo, capsys)
    text = "Deploy on any day"
    assert main(["add", text, "--supersedes", fact, "--kind", "rule"]) == 0
    capsys.readouterr()
    assert text in load(capsys)[0]


def test_strict_agrees_with_the_load_that_a_plain_word_can_stay(repo, mem, capsys):
    owner_rule(repo, capsys)
    assert "leave" in load(capsys)[1].lower()
    assert main(["check", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "deploy-bot" not in out and "also uses" in out


def test_strict_still_fails_on_a_value_with_its_own_shape(repo, mem, capsys):
    assert main(["add", "The staging login uses abc123xyz789 today"]) == 0
    (repo / ".env").write_text("API_TOKEN=abc123xyz789\n")
    capsys.readouterr()
    assert main(["check", "--strict"]) == 1
    assert "abc123xyz789" not in capsys.readouterr().out
