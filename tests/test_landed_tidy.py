"""`memory tidy` and the session start propose to end a one-time approval whose work landed.

A fact that a person stated is the owner's to end: the proposal says to ask the owner, and
`memory tidy --apply` does not end it.
"""

from __future__ import annotations

import io
import json
import re

from test_landed import add, at, commit

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project


def tidy(capsys, *args: str) -> str:
    capsys.readouterr()
    assert main(["tidy", *args]) == 0
    return capsys.readouterr().out


def status(mem, fid: str) -> str:
    return Memory.open(find_project(mem.parent / "proj"), None).fact(fid)["status"]


def agent_add(capsys, monkeypatch, *args: str) -> str:
    monkeypatch.setenv("CLAUDECODE", "1")
    fid = add(capsys, *args)
    monkeypatch.delenv("CLAUDECODE")
    return fid


def landed_work(repo, capsys, monkeypatch) -> dict[str, str]:
    """A told rule and an agent's decision whose files landed, a lesson, and an open rule."""
    at(monkeypatch, "05")
    commit(repo, "base", {"src/app.py": "v1\n", "db/0018.sql": "a\n"})
    at(monkeypatch, "10")
    ids = {
        "rule": add(
            capsys,
            "Yes to migration 0018.",
            "--kind",
            "rule",
            "--files",
            "db/0018.sql",
            "--basis",
            "told",
        ),
        "decision": agent_add(
            capsys,
            monkeypatch,
            "Go ahead with the app split.",
            "--kind",
            "decision",
            "--basis",
            "seen",
            "--files",
            "src/app.py",
        ),
        "lesson": add(
            capsys, "The app split was slow.", "--kind", "lesson", "--files", "src/app.py"
        ),
        "open": add(
            capsys,
            "Yes to the docs pass.",
            "--kind",
            "rule",
            "--files",
            "docs/a.md",
            "--basis",
            "seen",
        ),
    }
    at(monkeypatch, "12")
    commit(repo, "Land 0018 and the app split", {"src/app.py": "v2\n", "db/0018.sql": "b\n"})
    return ids


def line_of(out: str, fid: str) -> str:
    return next(line for line in out.splitlines() if f"[landed] {fid}" in line)


def proposal_id(line: str) -> str:
    return re.search(r"- (p-[0-9a-f]+) ", line).group(1)


def test_tidy_proposes_to_end_each_approval_whose_work_landed(mem, repo, capsys, monkeypatch):
    ids = landed_work(repo, capsys, monkeypatch)
    out = tidy(capsys)
    for kind in ("rule", "decision"):
        fid = ids[kind]
        line = line_of(out, fid)
        assert "2026-10-12" in line and "Land 0018 and the app split" in line
        assert f'memory change {fid} --status expired --reason "Work landed in ' in line
    assert ids["lesson"] not in out, "only a rule or a decision is about to be ended"
    assert ids["open"] not in out, "docs/a.md has no commit"
    assert status(mem, ids["rule"]) == "active", "tidy ends nothing"


def test_a_told_rule_asks_the_owner_and_apply_skips_it(mem, repo, capsys, monkeypatch):
    ids = landed_work(repo, capsys, monkeypatch)
    out = tidy(capsys)
    told, agents = line_of(out, ids["rule"]), line_of(out, ids["decision"])
    assert "ask the owner" in told and f"memory change {ids['rule']} --status expired" in told
    assert "ask the owner" not in agents
    applied = tidy(capsys, "--apply", proposal_id(told), proposal_id(agents))
    assert "skipped" in applied and ids["rule"] in applied and "ask the owner" in applied
    assert status(mem, ids["rule"]) == "active", "the owner ends a told rule"
    assert status(mem, ids["decision"]) == "expired"


def test_the_session_start_names_them_and_retires_none(mem, repo, capsys, monkeypatch):
    (mem / "config.toml").write_text('auto_tidy = "on"\n')
    ids = landed_work(repo, capsys, monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    out = capsys.readouterr().out
    note = next(line for line in out.splitlines() if "landed on the main branch" in line)
    assert ids["rule"] in note and ids["decision"] in note and "`memory tidy`" in note
    assert f"A person stated {ids['rule']}: ask the owner" in note
    assert ids["open"] not in note
    assert status(mem, ids["rule"]) == "active" and status(mem, ids["decision"]) == "active"


def test_a_newer_fact_that_replaces_a_rule_in_words_is_proposed(mem, repo, capsys, monkeypatch):
    at(monkeypatch, "10")
    old = add(capsys, "Run the slow suite before each push.", "--kind", "rule", "--basis", "seen")
    at(monkeypatch, "11")
    new = add(
        capsys,
        f"Run only the fast suite before a push; this replaces {old}.",
        "--kind",
        "decision",
        "--basis",
        "seen",
    )
    out = tidy(capsys)
    line = next(line for line in out.splitlines() if "[replaced-in-words]" in line)
    assert old in line and new in line
    assert "--apply" in out
