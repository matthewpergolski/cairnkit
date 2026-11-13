"""`memory change` takes several IDs with one set of flags. All of them change, or none does.

`--held-by` must be a file in the repo. A file that holds none of the words of a fact gets a note.
"""

from __future__ import annotations

import pytest
from conftest import git, read_jsonl

from cairnkit.cli import main

BASE = ["--area", "deploy", "--basis", "seen", "--source", "commit:abc1234"]


def add(capsys, text, *extra):
    capsys.readouterr()
    assert main(["add", text, *BASE, *extra]) == 0
    return capsys.readouterr().out.split("added ")[1].split()[0]


def status(mem, fid):
    changes = [r for r in read_jsonl(mem / "facts" / "main.jsonl") if r["id"] == fid]
    return changes[-1]["status"], changes[-1].get("held_by")


def run(capsys, *argv):
    capsys.readouterr()
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def commit(repo, rel, text):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", rel)
    git(repo, "commit", "-qm", f"add {rel}")


def as_agent(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s")


def test_several_ids_are_promoted_in_one_command(mem, repo, capsys):
    commit(repo, "skills/deploy/SKILL.md", "Deploys need a clean tree. Tag after the release.\n")
    ids = [add(capsys, "Deploys need a clean tree."), add(capsys, "Tag after the release.")]
    code, out = run(
        capsys,
        "change",
        *ids,
        "--status",
        "promoted",
        "--held-by",
        "skills/deploy/SKILL.md",
        "--reason",
        "the deploy skill holds it",
    )
    assert code == 0, out
    for fid in ids:
        assert status(mem, fid) == ("promoted", "skills/deploy/SKILL.md")
        assert f"changed {fid}" in out
    assert "note:" not in out


def test_one_refused_id_changes_none(mem, capsys):
    fid = add(capsys, "Deploys need a clean tree.")
    code, out = run(
        capsys, "change", fid, "f-20260101-0000", "--status", "expired", "--reason", "r"
    )
    assert code == 1 and "f-20260101-0000" in out
    assert status(mem, fid) == ("active", None)


def test_each_id_keeps_the_authority_guard(mem, capsys, monkeypatch):
    mine = add(capsys, "Deploys run from main.")
    owner = add(capsys, "Deploys run on Fridays only.", "--basis", "told")
    as_agent(monkeypatch)
    new = add(capsys, "Deploys run any day.")
    code, out = run(
        capsys,
        "change",
        mine,
        owner,
        "--status",
        "superseded",
        "--superseded-by",
        new,
        "--reason",
        "r",
    )
    assert code == 1 and f"{owner}: {owner} was stated by a person" in out
    assert status(mem, mine) == ("active", None)
    assert status(mem, owner) == ("active", None)


@pytest.mark.parametrize("where", ["../outside.md", "docs"])
def test_held_by_must_be_a_file_in_the_repo(mem, repo, capsys, where):
    (repo.parent / "outside.md").write_text("Deploys need a clean tree.\n")
    (repo / "docs").mkdir()
    fid = add(capsys, "Deploys need a clean tree.")
    code, _ = run(
        capsys, "change", fid, "--status", "promoted", "--held-by", where, "--reason", "r"
    )
    assert code == 1
    assert status(mem, fid) == ("active", None)


def test_a_held_by_file_without_the_words_names_the_right_one(mem, repo, capsys):
    commit(repo, "skills/deploy/SKILL.md", "Run the release script only on a clean tree.\n")
    commit(repo, "skills/format/SKILL.md", "Format code with ruff before review.\n")
    fid = add(capsys, "The release script needs a clean tree.")
    code, out = run(
        capsys,
        "change",
        fid,
        "--status",
        "promoted",
        "--held-by",
        "skills/format/SKILL.md",
        "--reason",
        "r",
    )
    assert code == 0
    assert status(mem, fid) == ("promoted", "skills/format/SKILL.md")
    note = next(line for line in out.splitlines() if line.startswith("note: skills/format"))
    assert fid in note
    assert f"memory change {fid} --status promoted --held-by skills/deploy/SKILL.md" in note


def test_an_untracked_held_by_file_gets_a_note(mem, repo, capsys):
    (repo / "RULES.md").write_text("The release script needs a clean tree.\n")
    fid = add(capsys, "The release script needs a clean tree.")
    code, out = run(
        capsys, "change", fid, "--status", "promoted", "--held-by", "RULES.md", "--reason", "r"
    )
    assert code == 0
    assert status(mem, fid) == ("promoted", "RULES.md")
    assert "note: git does not track RULES.md" in out
