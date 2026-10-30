"""Review pending candidates without treating them as facts.

`memory candidates` lists what is still pending. `--accept` writes a real fact
from the stored area, basis, and source. `--dismiss` drops the candidate.
`memory add` of the same text marks the pending row accepted. `memory load`
stays quiet until that write.
"""

from __future__ import annotations

import json

from conftest import git

from cairnkit.cli import main

TEXT = "The release job must wait for a clean worktree before it ships."
CID = "c-20261030-ab12"


def seed(mem, **overrides) -> str:
    rec = {
        "type": "candidate",
        "id": CID,
        "status": "pending",
        "text": TEXT,
        "kind": "lesson",
        "area": "deploy",
        "basis": "guess",
        "source": "commit:abc1234def56",
        "origin": "draft",
        "at": "2026-10-30T12:00:00+00:00",
        "created_at": "2026-10-30T12:00:00+00:00",
    }
    rec.update(overrides)
    path = mem / "proposals" / "auto-candidates.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rec["id"]


def facts(mem) -> list[dict]:
    rows = []
    for path in (mem / "facts").glob("*.jsonl"):
        for line in path.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def test_bare_candidates_lists_pending_and_load_hides_the_text(mem, capsys):
    seed(mem)
    capsys.readouterr()
    assert main(["candidates"]) == 0
    listed = capsys.readouterr().out
    assert CID in listed and TEXT in listed
    assert main(["load"]) == 0
    loaded = capsys.readouterr().out
    assert TEXT not in loaded
    assert CID not in loaded


def test_dismiss_drops_the_candidate_from_the_list(mem, capsys):
    seed(mem)
    capsys.readouterr()
    assert main(["candidates", "--dismiss", CID]) == 0
    capsys.readouterr()
    assert main(["candidates"]) == 0
    listed = capsys.readouterr().out
    assert "No pending" in listed
    assert CID not in listed


def test_accept_writes_the_stored_basis_area_and_source(mem, capsys):
    seed(mem)
    capsys.readouterr()
    assert main(["candidates", "--accept", CID]) == 0
    assert main(["load"]) == 0
    assert TEXT in capsys.readouterr().out
    written = [row for row in facts(mem) if row.get("type") == "fact" and row.get("text") == TEXT]
    assert written
    fact = written[0]
    assert fact["basis"] == "guess"
    assert fact["area"] == "deploy"
    assert fact["source"] == "commit:abc1234def56"
    assert fact["kind"] == "lesson"


def test_accept_refuses_a_candidate_with_no_source(mem, capsys):
    seed(mem, source="")
    capsys.readouterr()
    assert main(["candidates", "--accept", CID]) != 0
    assert main(["load"]) == 0
    assert TEXT not in capsys.readouterr().out


def test_add_of_the_same_text_accepts_the_pending_candidate(mem, capsys):
    seed(mem)
    capsys.readouterr()
    assert (
        main(
            [
                "add",
                TEXT,
                "--kind",
                "lesson",
                "--area",
                "deploy",
                "--basis",
                "told",
                "--source",
                "commit:abc1234def56",
            ]
        )
        == 0
    )
    assert main(["candidates"]) == 0
    assert CID not in capsys.readouterr().out
    assert main(["load"]) == 0
    assert TEXT in capsys.readouterr().out


def test_a_post_commit_draft_stores_guess_and_at(repo, mem, capsys):
    (repo / "note.txt").write_text("body\n")
    git(repo, "add", "note.txt")
    git(repo, "commit", "-q", "-m", "lesson: deploys need a clean tree before release")
    capsys.readouterr()
    assert main(["hook", "post-commit"]) == 0
    path = mem / "proposals" / "auto-candidates.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    drafted = [row for row in rows if row.get("type") == "candidate"]
    assert drafted
    assert drafted[0]["basis"] == "guess"
    assert drafted[0].get("at")
