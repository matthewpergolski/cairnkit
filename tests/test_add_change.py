import re
from datetime import datetime, timedelta

import pytest
from conftest import add_worktree, read_jsonl

from cairnkit.cli import main

ID_RE = re.compile(r"^f-\d{8}-[0-9a-f]{4}$")
BASE = ["--area", "deploy", "--basis", "seen", "--source", "commit:abc1234"]


def add(capsys, text, *extra):
    capsys.readouterr()
    assert main(["add", text, *BASE, *extra]) == 0
    return capsys.readouterr().out.strip().splitlines()[-1].split()[-1]


def test_add_writes_one_fact_line(mem, capsys):
    fid = add(capsys, "Deploys need a clean tree.", "--kind", "trap", "--tag", "git")
    assert ID_RE.match(fid)
    [rec] = read_jsonl(mem / "facts" / "main.jsonl")
    assert rec["type"] == "fact" and rec["id"] == fid
    assert rec["kind"] == "trap" and rec["area"] == "deploy" and rec["tags"] == ["git"]
    assert rec["basis"] == "seen" and rec["source"] == "commit:abc1234"
    assert rec["status"] == "active" and rec["writer"] == "main"
    assert rec["scope"] == "long"
    assert datetime.fromisoformat(rec["learned_at"]).tzinfo is not None
    assert rec["happened_at"]


def test_each_writer_gets_its_own_file(repo, mem, capsys, monkeypatch):
    wt = add_worktree(repo, "feature-x")
    main(["init", "--no-default-rules"])
    monkeypatch.chdir(wt)
    add(capsys, "Worktree fact.")
    assert (mem / "facts" / "feature-x.jsonl").is_file()
    monkeypatch.setenv("MEMORY_WRITER", "night job")
    add(capsys, "Job fact.")
    assert (mem / "facts" / "night-job.jsonl").is_file()


def test_earlier_bytes_never_change(mem, capsys):
    first = add(capsys, "First fact.")
    path = mem / "facts" / "main.jsonl"
    before = path.read_bytes()
    add(capsys, "Second fact.", "--supersedes", first)
    assert main(["change", first, "--status", "wrong", "--reason", "Bad guess."]) == 0
    after = path.read_bytes()
    assert after.startswith(before)
    assert len(after) > len(before)


def test_refuses_long_text_and_secrets(mem, capsys):
    assert main(["add", "x" * 2001, *BASE]) != 0
    assert main(["add", "Key is AKIAABCDEFGHIJKLMNOP now.", *BASE]) != 0
    assert "secret" in capsys.readouterr().err.lower()
    assert not (mem / "facts" / "main.jsonl").exists()


def test_supersedes_writes_fact_and_change(mem, capsys):
    old = add(capsys, "Two database projects.")
    new = add(capsys, "One database project.", "--supersedes", old, "--reason", "Free tier.")
    recs = read_jsonl(mem / "facts" / "main.jsonl")
    change = recs[-1]
    assert change["type"] == "change" and change["id"] == old
    assert change["status"] == "superseded" and change["superseded_by"] == new
    assert change["reason"] == "Free tier."


def test_supersedes_unknown_id_is_refused(mem, capsys):
    assert main(["add", "New.", *BASE, "--supersedes", "f-20260101-0000"]) != 0
    assert not (mem / "facts" / "main.jsonl").exists()


def test_change_rules(repo, mem, capsys):
    fid = add(capsys, "A rule.")
    other = add(capsys, "Another.")
    assert main(["change", fid, "--status", "wrong"]) != 0  # reason required
    assert main(["change", "f-20260101-0000", "--status", "wrong", "--reason", "x"]) != 0
    assert main(["change", fid, "--status", "superseded", "--reason", "x"]) != 0
    assert main(["change", fid, "--status", "promoted", "--reason", "x"]) != 0
    args = ["change", fid, "--status", "promoted", "--reason", "x", "--held-by", "nope.md"]
    assert main(args) != 0
    with pytest.raises(SystemExit):
        main(["change", fid, "--status", "bogus", "--reason", "x"])
    assert main([*args[:-1], "README.md"]) == 0
    assert main(["change", other, "--link", f"related:{fid}"]) == 0
    recs = read_jsonl(mem / "facts" / "main.jsonl")
    assert recs[-2]["held_by"] == "README.md"
    assert recs[-1]["add_links"] == [{"rel": "related", "id": fid}]


def test_short_term_fact_gets_expiry(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", "2026-10-01T12:00:00-05:00")
    add(capsys, "Working note.", "--short")
    [rec] = read_jsonl(mem / "facts" / "main.jsonl")
    assert rec["scope"] == "short"
    learned = datetime.fromisoformat(rec["learned_at"])
    assert datetime.fromisoformat(rec["expires_at"]) - learned == timedelta(days=14)


def test_short_term_days_comes_from_config(mem, capsys, monkeypatch):
    cfg = mem / "config.toml"
    cfg.write_text(cfg.read_text().replace("short_term_days = 14", "short_term_days = 3"))
    monkeypatch.setenv("MEMORY_NOW", "2026-10-01T12:00:00-05:00")
    add(capsys, "Working note.", "--short")
    [rec] = read_jsonl(mem / "facts" / "main.jsonl")
    assert rec["expires_at"].startswith("2026-10-04")


def test_until_merged_uses_current_branch(repo, mem, capsys, monkeypatch):
    wt = add_worktree(repo, "feature-z")
    monkeypatch.chdir(wt)
    add(capsys, "Branch note.", "--short", "--until-merged")
    [rec] = read_jsonl(mem / "facts" / "feature-z.jsonl")
    assert rec["until_branch_merged"] == "feature-z"


def test_keep_turns_short_into_long(mem, capsys):
    fid = add(capsys, "Working note.", "--short")
    assert main(["keep", fid, "--reason", "Still true after the branch."]) == 0
    change = read_jsonl(mem / "facts" / "main.jsonl")[-1]
    assert change["type"] == "change" and change["scope"] == "long"
    assert main(["keep", fid, "--reason", "again"]) != 0  # already long


def test_promote_is_a_hidden_alias_of_keep(mem, capsys):
    fid = add(capsys, "Working note.", "--short")
    assert main(["promote", fid]) == 0
    assert read_jsonl(mem / "facts" / "main.jsonl")[-1]["scope"] == "long"
    capsys.readouterr()
    main([])
    assert "promote" not in capsys.readouterr().out
