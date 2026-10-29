"""Stop hook: junk stays quiet, durable work reminds once, auto-tidy does not count."""

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


def test_stop_names_a_tracked_edit_and_says_you_can_finish(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    (repo / "README.md").write_text("changed\n")
    code, out, _ = stop(capsys, monkeypatch)
    assert code == 0
    data = json.loads(out)
    assert data["decision"] == "block"
    reason = data["reason"]
    assert "README.md" in reason
    assert "say so and finish" in reason
    _, again, _ = stop(capsys, monkeypatch)
    assert "block" not in again


def test_an_auto_tidy_write_does_not_suppress_the_reminder(repo, mem, capsys, monkeypatch):
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
    _, out, _ = stop(capsys, monkeypatch)
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "memory add" in data["reason"]
    assert "README.md" in data["reason"]


def test_a_session_file_without_the_durable_gate_rebaselines_quietly(
    repo, mem, capsys, monkeypatch
):
    folder = mem / ".sessions"
    folder.mkdir(exist_ok=True)
    (folder / "s1.json").write_text(
        json.dumps({"started_at": "2020-01-01T00:00:00+00:00", "start": "old-hash"})
    )
    (repo / "README.md").write_text("changed\n")
    code, out, _ = stop(capsys, monkeypatch)
    assert code == 0
    assert "block" not in out
    saved = json.loads((folder / "s1.json").read_text())
    assert saved.get("gate") == "durable"
    _, again, _ = stop(capsys, monkeypatch)
    assert "block" not in again
