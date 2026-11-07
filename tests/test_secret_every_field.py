"""Each free-form field that a write stores is scanned before the write, on each write path."""

from __future__ import annotations

from conftest import read_jsonl

from cairnkit.cli import main

TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"
RULE = ["--kind", "rule", "--area", "git", "--basis", "told", "--source", "person:owner"]
ADD = ["--area", "x", "--basis", "seen", "--source", "session:1"]


def stored(mem) -> str:
    return "".join(path.read_text() for path in (mem / "facts").glob("*.jsonl"))


def added(capsys, *argv: str) -> str:
    capsys.readouterr()
    assert main(["add", *argv]) == 0
    return capsys.readouterr().out.split()[1]


def test_add_refuses_a_secret_in_enforced_by(mem, capsys):
    assert main(["add", "lint runs in CI", *RULE, "--enforced-by", f"ci:{TOKEN}"]) == 1
    captured = capsys.readouterr()
    assert "GitHub token" in captured.err and TOKEN not in captured.out + captured.err
    assert TOKEN not in stored(mem)


def test_add_refuses_a_secret_as_the_end_branch(mem, capsys):
    assert main(["add", "a short note", *ADD, "--short", "--until-merged", TOKEN]) == 1
    assert "GitHub token" in capsys.readouterr().err
    assert TOKEN not in stored(mem)


def test_change_refuses_a_secret_in_enforced_by(mem, capsys):
    fid = added(capsys, "lint runs in CI", *RULE, "--enforced-by", "ci:lint")
    assert main(["change", fid, "--enforced-by", f"ci:{TOKEN}"]) == 1
    assert "GitHub token" in capsys.readouterr().err
    assert TOKEN not in stored(mem)


def test_an_ordinary_end_branch_and_check_are_still_stored(mem, capsys):
    fid = added(capsys, "lint runs in CI", *RULE, "--enforced-by", "ci:lint")
    assert main(["change", fid, "--enforced-by", "ci:unit"]) == 0
    added(capsys, "a short note", *ADD, "--short", "--until-merged", "feature-x")
    records = read_jsonl(mem / "facts" / "main.jsonl")
    assert [r.get("enforced_by") for r in records if r.get("enforced_by")] == ["ci:lint", "ci:unit"]
    assert records[-1]["until_branch_merged"] == "feature-x"


def test_change_refuses_a_secret_as_the_holding_file_and_never_prints_it(mem, capsys):
    fid = added(capsys, "lint runs in CI", *RULE)
    argv = ["change", fid, "--status", "promoted", "--held-by", TOKEN, "--reason", "moved"]
    assert main(argv) == 1
    captured = capsys.readouterr()
    assert "GitHub token" in captured.err and TOKEN not in captured.out + captured.err
