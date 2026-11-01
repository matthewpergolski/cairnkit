"""A secret that the memory folder does not hold: an old copy, git history, native memory."""

from __future__ import annotations

import io
import json

from conftest import git

from cairnkit.cli import main
from cairnkit.native import _claude_store

VALUE = "q1w2e3r4t5y6"


def run(capsys, *args) -> tuple[int, str]:
    capsys.readouterr()
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_check_names_a_secret_in_the_old_copy(repo, mem, capsys):
    old = repo.parent / f"{repo.name}.memory-old"
    (old / "notes").mkdir(parents=True)
    (old / "notes" / "old.txt").write_text(f"plain\nCRON_SECRET={VALUE}\n")
    code, out = run(capsys, "check")
    assert code == 0 and VALUE not in out
    assert f"{repo.name}.memory-old/notes/old.txt:2" in out
    assert run(capsys, "check", "--strict")[0] == 1
    (old / "notes" / "old.txt").write_text("plain\n")
    assert run(capsys, "check", "--strict")[0] == 0


def test_check_says_git_history_holds_what_was_committed(repo, mem, capsys, tmp_path):
    other = tmp_path / "side"
    other.mkdir()
    (repo / "memory-bank").rename(other / "link")
    (repo / "memory-bank").mkdir()
    (repo / "memory-bank" / "log.md").write_text(f"CRON_SECRET={VALUE}\n")
    git(repo, "add", "-f", "memory-bank/log.md")
    git(repo, "commit", "-qm", "old notes")
    git(repo, "rm", "-rqf", "--cached", "memory-bank")
    git(repo, "commit", "-qm", "untrack")
    (repo / "memory-bank" / "log.md").unlink()
    (repo / "memory-bank").rmdir()
    (other / "link").rename(repo / "memory-bank")
    code, out = run(capsys, "check")
    assert VALUE not in out
    assert "git history still holds" in out and "does not rewrite history" in out
    assert code == 0


def test_check_is_silent_about_a_clean_history(repo, mem, capsys):
    assert "git history" not in run(capsys, "check")[1]


def test_native_memory_is_named_with_no_value_and_is_not_edited(
    repo, mem, capsys, monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    store = _claude_store(repo)
    store.mkdir(parents=True)
    (store / "key.md").write_text(f"plain\nCRON_SECRET={VALUE}\n")
    (store / "ok.md").write_text("plain note\n")
    before = (store / "key.md").read_bytes()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s"})))
    code, out = run(capsys, "hook", "session-start", "--agent", "claude")
    assert code == 0 and VALUE not in out
    assert "key.md:2" in out and "looks secret" in out and "ok.md" not in out
    code, out = run(capsys, "check", "--strict")
    assert code == 0 and VALUE not in out and "key.md:2" in out
    assert (store / "key.md").read_bytes() == before
    (store / "key.md").write_text("plain\n")
    assert "key.md" not in run(capsys, "check")[1]
