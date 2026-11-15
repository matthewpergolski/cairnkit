"""Durable work earns one block. Junk stays quiet. Auto-tidy does not count as a fact."""

import io
import json
from datetime import timedelta

from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.clock import parse_time, stamp


def run_hook(capsys, monkeypatch, event, agent, payload=None):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload or {})))
    capsys.readouterr()
    code = main(["hook", event, "--agent", agent])
    out = capsys.readouterr()
    return code, out.out, out.err


def start(capsys, monkeypatch, sid="s1"):
    run_hook(capsys, monkeypatch, "session-start", "claude", {"session_id": sid})


def stop(capsys, monkeypatch, sid="s1"):
    return run_hook(capsys, monkeypatch, "stop", "claude", {"session_id": sid})


def test_stop_stays_quiet_for_junk_and_untracked_noise(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    (repo / "debug.log").write_text("noise\n")
    (repo / "scratch.tmp").write_text("x\n")
    cache = repo / "__pycache__"
    cache.mkdir()
    (cache / "mod.pyc").write_bytes(b"\0\0")
    code, out, _ = stop(capsys, monkeypatch)
    assert code == 0
    assert "block" not in out


def test_stop_stays_quiet_when_a_tracked_junk_file_changes(repo, mem, capsys, monkeypatch):
    """Tracked .log edits use the same junk filter as untracked paths."""
    import subprocess

    (repo / "debug.log").write_text("noise\n")
    subprocess.run(["git", "add", "debug.log"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "track log"], cwd=repo, check=True)
    start(capsys, monkeypatch)
    (repo / "debug.log").write_text("noise\nmore\n")
    code, out, _ = stop(capsys, monkeypatch)
    assert code == 0
    assert "block" not in out


def test_a_tracked_edit_blocks_the_stop_once(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    (repo / "README.md").write_text("changed\n")
    code, out, _ = stop(capsys, monkeypatch)
    assert code == 0
    assert "memory add" in json.loads(out)["reason"]
    (repo / "README.md").write_text("changed again\n")
    assert stop(capsys, monkeypatch)[1] == ""


def test_an_auto_tidy_write_does_not_end_the_check(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    (repo / "README.md").write_text("changed\n")
    saved = json.loads((mem / ".sessions" / "s1.json").read_text())
    later = stamp(parse_time(saved["started_at"]) + timedelta(seconds=5))
    write_facts(
        mem,
        [
            make_fact(
                "f-20261029-aa01",
                "Retired a duplicate.",
                learned_at=later,
                writer="auto-tidy",
            )
        ],
        name="auto-tidy.jsonl",
    )
    assert "memory add" in json.loads(stop(capsys, monkeypatch)[1])["reason"]


def test_a_session_file_from_an_older_tool_blocks_nothing(repo, mem, capsys, monkeypatch):
    folder = mem / ".sessions"
    folder.mkdir(exist_ok=True)
    (folder / "s1.json").write_text(
        json.dumps({"started_at": "2020-01-01T00:00:00+00:00", "start": "old-hash"})
    )
    (repo / "README.md").write_text("changed\n")
    code, out, _ = stop(capsys, monkeypatch)
    assert code == 0
    assert "block" not in out
    _, again, _ = stop(capsys, monkeypatch)
    assert "block" not in again
