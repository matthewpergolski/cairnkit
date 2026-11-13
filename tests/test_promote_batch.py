"""`memory change` takes several IDs with one set of flags. All of them change, or none does.

`--held-by` must be a file in the repo. A file that holds none of the words of a fact gets a note.
"""

from __future__ import annotations

import os
import subprocess
import sys

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
    assert "Nothing changed" not in out and out.count("No fact changed") == 1
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


def changes(mem, *fids):
    return [r for r in read_jsonl(mem / "facts" / "main.jsonl") if r["id"] in fids and "at" in r]


@pytest.mark.parametrize(
    "flags",
    [
        ("{A}", "--status", "superseded", "--superseded-by", "{A}", "--reason", "r"),
        ("{A}", "{B}", "--status", "superseded", "--superseded-by", "{B}", "--reason", "r"),
        ("{A}", "--link", "related:{A}"),
        ("{A}", "{B}", "--link", "related:{B}"),
    ],
)
def test_a_fact_cannot_replace_or_link_itself(mem, capsys, flags):
    ids = {"A": add(capsys, "Deploys need a clean tree."), "B": add(capsys, "Deploys need a tag.")}
    before = changes(mem, *ids.values())
    code, out = run(capsys, "change", *(word.format(**ids) for word in flags))
    assert code == 1 and "cannot replace itself or link to itself" in out
    assert changes(mem, *ids.values()) == before


@pytest.mark.parametrize("end", ["expired", "wrong"])
def test_an_agent_cannot_end_the_owner_fact(mem, capsys, monkeypatch, end):
    mine = add(capsys, "Deploys run from main.")
    owner = add(capsys, "Deploys run on Fridays only.", "--basis", "told")
    as_agent(monkeypatch)
    for ids in ([owner], [mine, owner]):
        code, out = run(capsys, "change", *ids, "--status", end, "--reason", "r")
        assert code == 1 and f"a person stated {owner}," in out
        assert f'Ask the owner "Shall I end {owner}?"' in out
        assert f"run: memory change {' '.join(ids)} --status {end}" in out
        assert "own shell" in out
    assert status(mem, owner) == ("active", None) and status(mem, mine) == ("active", None)


def test_an_agent_can_promote_the_owner_fact_and_the_owner_can_end_it(
    mem, repo, capsys, monkeypatch
):
    commit(repo, "RULES.md", "Deploys run on Fridays only.\n")
    first = add(capsys, "Deploys run on Fridays only.", "--basis", "told")
    second = add(capsys, "Releases need two reviewers.", "--basis", "told")
    code, _ = run(capsys, "change", second, "--status", "expired", "--reason", "r")
    assert code == 0, "the owner at a terminal ends it"
    as_agent(monkeypatch)
    promote = ("--status", "promoted", "--held-by", "RULES.md", "--reason", "r")
    code, out = run(capsys, "change", first, *promote)
    assert code == 0, out
    assert status(mem, first) == ("promoted", "RULES.md")


def run_cli(repo, *args):
    """The CLI in its own process, so that a hang fails the test and does not stop the run."""
    argv = [sys.executable, "-m", "cairnkit", *args]
    return subprocess.run(argv, cwd=repo, capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize("where", ["pipe.md", "link.md"])
def test_held_by_on_a_pipe_is_refused_at_once(mem, repo, capsys, where):
    os.mkfifo(repo / "pipe.md")
    (repo / "link.md").symlink_to("pipe.md")
    fid = add(capsys, "Deploys need a clean tree.")
    done = run_cli(repo, "change", fid, "--status", "promoted", "--held-by", where, "--reason", "r")
    assert done.returncode == 1 and "is no regular file" in done.stderr
    assert status(mem, fid) == ("active", None)


def test_a_pipe_or_a_device_beside_held_by_does_not_hang(mem, repo, capsys):
    commit(repo, "skills/a.md", "Format code with ruff.\n")
    os.mkfifo(repo / "skills" / "b.md")
    (repo / "skills" / "c.md").symlink_to("/dev/zero")
    fid = add(capsys, "Deploys need a clean tree.")
    promote = ("--status", "promoted", "--held-by", "skills/a.md", "--reason", "r")
    done = run_cli(repo, "change", fid, *promote)
    assert done.returncode == 0, done.stderr
    assert "holds none of the key words" in done.stdout


@pytest.mark.parametrize(
    "where",
    ["link.md", "linkdir/outside.md", ".git/config", "memory-bank/facts/main.jsonl"],
)
def test_held_by_cannot_lead_out_of_the_repo_or_into_git_or_the_memory(mem, repo, capsys, where):
    (repo.parent / "outside.md").write_text("Deploys need a clean tree.\n")
    (repo / "link.md").symlink_to(repo.parent / "outside.md")
    (repo / "linkdir").symlink_to(repo.parent)
    assert (repo / "memory-bank").is_symlink()
    fid = add(capsys, "Deploys need a clean tree.")
    promote = ("--status", "promoted", "--held-by", where, "--reason", "r")
    code, out = run(capsys, "change", fid, *promote)
    assert code == 1 and "Name the repo file that holds the rule" in out, out
    assert status(mem, fid) == ("active", None)


def test_held_by_through_a_link_inside_the_repo_is_kept(mem, repo, capsys):
    commit(repo, "docs/RULES.md", "Deploys need a clean tree.\n")
    (repo / "rules.md").symlink_to("docs/RULES.md")
    fid = add(capsys, "Deploys need a clean tree.")
    promote = ("--status", "promoted", "--held-by", "rules.md", "--reason", "r")
    code, out = run(capsys, "change", fid, *promote)
    assert code == 0, out
    assert status(mem, fid) == ("promoted", "rules.md")
