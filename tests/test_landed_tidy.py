"""`memory tidy` and the session start propose to end a rule or decision whose work landed."""

from __future__ import annotations

import io
import json

from conftest import read_jsonl
from test_landed import add, at, commit

from cairnkit.cli import main


def tidy(capsys) -> str:
    capsys.readouterr()
    assert main(["tidy"]) == 0
    return capsys.readouterr().out


def status(mem, fid: str) -> str:
    records = [r for f in (mem / "facts").glob("*.jsonl") for r in read_jsonl(f)]
    changes = [r for r in records if r.get("id") == fid and r.get("status")]
    return changes[-1]["status"]


def landed_work(repo, capsys, monkeypatch) -> dict[str, str]:
    """A told rule and a decision whose files landed, and a lesson and a rule that did not."""
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
            "seen",
        ),
        "decision": add(
            capsys, "Go ahead with the app split.", "--kind", "decision", "--files", "src/app.py"
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


def test_tidy_proposes_to_end_each_rule_and_decision_whose_work_landed(
    mem, repo, capsys, monkeypatch
):
    ids = landed_work(repo, capsys, monkeypatch)
    out = tidy(capsys)
    for kind in ("rule", "decision"):
        fid = ids[kind]
        line = next(line for line in out.splitlines() if f"[landed] {fid}" in line)
        assert "2026-10-12" in line and "Land 0018 and the app split" in line
        assert f'memory change {fid} --status expired --reason "Work landed in ' in line
    assert ids["lesson"] not in out, "only a rule or a decision is about to be ended"
    assert ids["open"] not in out, "docs/a.md has no commit"
    assert status(mem, ids["rule"]) == "active", "tidy ends nothing"


def test_the_session_start_names_them_and_retires_none(mem, repo, capsys, monkeypatch):
    (mem / "config.toml").write_text('auto_tidy = "on"\n')
    ids = landed_work(repo, capsys, monkeypatch)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    out = capsys.readouterr().out
    note = next(line for line in out.splitlines() if "landed on the main branch" in line)
    assert ids["rule"] in note and ids["decision"] in note and "`memory tidy`" in note
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
