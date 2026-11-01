"""A correction from the owner or a lost file is named once at stop. The tool writes no fact."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from conftest import FIXTURES, git, read_jsonl

from cairnkit.cli import main
from cairnkit.signals import is_correction

ASK = "Does a trap belong in memory?"


def hook(capsys, monkeypatch, event: str, payload: dict, agent: str = "claude") -> str:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    capsys.readouterr()
    assert main(["hook", event, "--agent", agent]) == 0
    return capsys.readouterr().out


def start(capsys, monkeypatch, session: str = "s", agent: str = "claude") -> None:
    payload = {"session_id": session, "source": "startup"}
    hook(capsys, monkeypatch, "session-start", payload, agent)


def stop_text(capsys, monkeypatch, session: str = "s", agent: str = "claude") -> str:
    out = hook(capsys, monkeypatch, "stop", {"session_id": session}, agent)
    if not out.strip():
        return ""
    data = json.loads(out)
    return data.get("reason") or data.get("followup_message") or ""


def env_file(repo: Path) -> Path:
    (repo / ".gitignore").write_text(".worktrees/\n.env.local\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore")
    path = repo / ".env.local"
    path.write_text("A_NAME=1\n")
    return path


def test_the_reported_moment_is_named_once(repo, mem, capsys, monkeypatch):
    path = env_file(repo)
    start(capsys, monkeypatch)
    path.unlink()
    hook(capsys, monkeypatch, "prompt", {"session_id": "s", "prompt": "you deleted my env file"})
    text = stop_text(capsys, monkeypatch)
    assert "you deleted my env file" in text
    assert ".env.local" not in text, "the owner named it already"
    assert ASK in text
    assert stop_text(capsys, monkeypatch) == ""


def test_a_file_that_was_here_at_the_start_and_is_gone_is_named(repo, mem, capsys, monkeypatch):
    path = env_file(repo)
    start(capsys, monkeypatch)
    path.unlink()
    text = stop_text(capsys, monkeypatch)
    assert ".env.local" in text and ASK in text
    assert stop_text(capsys, monkeypatch) == ""


def test_a_tracked_file_gone_with_or_without_a_commit_is_named(repo, mem, capsys, monkeypatch):
    (repo / "keep.py").write_text("x = 1\n")
    git(repo, "add", "keep.py")
    git(repo, "commit", "-q", "-m", "add")
    start(capsys, monkeypatch)
    git(repo, "rm", "-q", "keep.py")
    git(repo, "commit", "-q", "-m", "drop")
    assert "keep.py" in stop_text(capsys, monkeypatch)


def test_a_file_made_in_this_session_is_not_named(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    made = repo / "scratch.txt"
    made.write_text("x")
    made.unlink()
    assert "scratch.txt" not in stop_text(capsys, monkeypatch)


@pytest.mark.parametrize(
    "name", ["build/out.bin", "node_modules/a.js", "trace.log", ".pytest_cache/v"]
)
def test_filler_is_not_named(repo, mem, capsys, monkeypatch, name):
    path = repo / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("x")
    start(capsys, monkeypatch)
    path.unlink()
    assert stop_text(capsys, monkeypatch) == ""


def test_a_file_the_owner_asked_to_delete_is_not_named(repo, mem, capsys, monkeypatch):
    path = env_file(repo)
    start(capsys, monkeypatch)
    prompt = {"session_id": "s", "prompt": "please delete .env.local, it is old"}
    hook(capsys, monkeypatch, "prompt", prompt)
    path.unlink()
    assert stop_text(capsys, monkeypatch) == ""


def test_a_moved_file_is_not_named(repo, mem, capsys, monkeypatch):
    (repo / "old.py").write_text("x = 1\n" * 20)
    git(repo, "add", "old.py")
    git(repo, "commit", "-q", "-m", "add")
    start(capsys, monkeypatch)
    git(repo, "mv", "old.py", "new.py")
    assert "old.py" not in stop_text(capsys, monkeypatch)


def test_a_branch_switch_is_not_a_deletion(repo, mem, capsys, monkeypatch):
    git(repo, "switch", "-q", "-c", "feat")
    (repo / "feat.py").write_text("x = 1\n")
    git(repo, "add", "feat.py")
    git(repo, "commit", "-q", "-m", "feat")
    start(capsys, monkeypatch)
    git(repo, "switch", "-q", "main")
    assert "feat.py" not in stop_text(capsys, monkeypatch)


def test_a_fact_written_after_a_correction_ends_the_question(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    hook(capsys, monkeypatch, "prompt", {"session_id": "s", "prompt": "that's wrong, it is 7643"})
    assert main(["add", "The port is 7643", "--basis", "told", "--source", "person:owner"]) == 0
    assert ASK not in stop_text(capsys, monkeypatch)


def test_a_fact_that_names_the_file_ends_the_question(repo, mem, capsys, monkeypatch):
    path = env_file(repo)
    start(capsys, monkeypatch)
    path.unlink()
    assert (
        main(["add", "Trap: .env.local is not in git, so a delete loses it", "--kind", "trap"]) == 0
    )
    assert ASK not in stop_text(capsys, monkeypatch)


def test_the_tool_writes_no_fact(repo, mem, capsys, monkeypatch):
    path = env_file(repo)
    start(capsys, monkeypatch)
    path.unlink()
    hook(capsys, monkeypatch, "prompt", {"session_id": "s", "prompt": "you deleted my env file"})
    stop_text(capsys, monkeypatch)
    assert not list((mem / "facts").glob("*.jsonl")) or not any(
        read_jsonl(path) for path in (mem / "facts").glob("*.jsonl")
    )


def test_a_secret_in_the_prompt_is_not_repeated_or_kept(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    prompt = {"session_id": "s", "prompt": "that's wrong, password=hunter2hunter2 is the old one"}
    hook(capsys, monkeypatch, "prompt", prompt)
    state = "".join(path.read_text() for path in (mem / ".sessions").glob("*.json"))
    assert "hunter2hunter2" not in state
    text = stop_text(capsys, monkeypatch)
    assert "hunter2hunter2" not in text and ASK in text


def test_cursor_records_the_prompt_and_answers_with_continue(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch, agent="cursor")
    payload = {"session_id": "s", "prompt": "you broke the login page"}
    assert json.loads(hook(capsys, monkeypatch, "prompt", payload, "cursor")) == {"continue": True}
    assert "you broke the login page" in stop_text(capsys, monkeypatch, agent="cursor")


def test_cursor_prompt_hook_answers_with_no_memory(repo, capsys, monkeypatch):
    payload = {"session_id": "s", "prompt": "hello"}
    assert json.loads(hook(capsys, monkeypatch, "prompt", payload, "cursor")) == {"continue": True}


def labelled(split: str) -> list[dict]:
    rows = [json.loads(line) for line in (FIXTURES / "correction_prompts.jsonl").open()]
    return [row for row in rows if row["split"] == split]


@pytest.mark.parametrize(("split", "most_false"), [("tune", 0), ("held", 1)])
def test_false_nudges_stay_rare(split, most_false):
    rows = labelled(split)
    false = [
        row["prompt"] for row in rows if not row["correction"] and is_correction(row["prompt"])
    ]
    assert len(false) <= most_false, false


@pytest.mark.parametrize(("split", "most_missed"), [("tune", 0), ("held", 2)])
def test_most_corrections_are_seen(split, most_missed):
    rows = labelled(split)
    missed = [
        row["prompt"] for row in rows if row["correction"] and not is_correction(row["prompt"])
    ]
    assert len(missed) <= most_missed, missed


def test_the_text_of_a_stop_is_never_a_correction(repo, mem, capsys, monkeypatch):
    """Cursor and OpenCode send a follow-up as a prompt, so a stop must not feed itself."""
    (repo / "a.py").write_text("x = 1\n")
    git(repo, "add", "a.py")
    git(repo, "commit", "-q", "-m", "a")
    start(capsys, monkeypatch)
    (repo / "a.py").unlink()
    hook(capsys, monkeypatch, "prompt", {"session_id": "s", "prompt": "that's wrong"})
    text = stop_text(capsys, monkeypatch)
    assert ASK in text
    assert not is_correction(text)
    assert not is_correction(f"{os.linesep}{text}")
