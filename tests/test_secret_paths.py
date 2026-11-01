"""A secret must not reach an agent or stay on disk through a path other than a fact."""

from __future__ import annotations

import io
import json

import pytest
from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.secretscan import find_secrets

ADD = ["--area", "x", "--basis", "seen", "--source", "session:1"]
NOTE_SECRET = "CRON_SECRET=q1w2e3r4t5y6"
BEARER = "abcdef1234567890abcdef"
CURL = f'curl -H "Authorization: Bearer {BEARER}" https://api.example.com'


def hook(capsys, monkeypatch, event, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    capsys.readouterr()
    main(["hook", event, "--agent", "claude"])
    return capsys.readouterr().out


def failed(command):
    return {
        "session_id": "s",
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "error": "Exit code 1",
        "is_interrupt": False,
    }


def every_file(mem) -> str:
    found = []
    for path in mem.rglob("*"):
        if path.is_file():
            found.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(found)


@pytest.mark.parametrize(
    "text",
    [
        "SECRET_KEY_BASE=abcdef1234567",
        "SESSION_COOKIE=abcd1234efgh5678",
        "export NPM_AUTH=abcdef123456",
        "cron_secret=q1w2e3r4t5y6",
        "whsec_abcdef1234567890abcdef",
        "npm_abcdefghijklmnopqrstuvwxyz0123456789",
        "glpat-abcdefgh12345678ijkl",
        "sb_secret_abcdef1234567890abcd",
        "Authorization: Basic dXNlcjpwYXNzd29yZA==",
        'curl -H "authorization: basic dXNlcjpwYXNzd29yZA=="',
    ],
)
def test_the_audit_shapes_are_refused(text):
    assert find_secrets(text)


@pytest.mark.parametrize(
    "text",
    [
        "the npm_config_registry variable sets the registry",
        "Authorization: Basic auth is off on staging",
        "Authorization: Basic $CREDENTIALS",
        "NPM_AUTH=$NPM_AUTH",
        "use_auth=true",
        "SESSION_COOKIE=$COOKIE",
        "cookie: session",
        "const sessionCookie = (await cookies()).get('session-id')",
    ],
)
def test_their_ordinary_neighbours_pass(text):
    assert find_secrets(text) == []


def test_a_note_secret_stays_out_of_the_session_and_stop_names_it(mem, capsys, monkeypatch):
    (mem / "notes" / "status.md").write_text(f"Working on it.\n{NOTE_SECRET}\n")
    out = hook(capsys, monkeypatch, "session-start", {"session_id": "s", "source": "startup"})
    assert "q1w2e3r4t5y6" not in out
    assert "Working on it." in out and "remove that line" in out
    out = hook(capsys, monkeypatch, "stop", {"session_id": "s"})
    assert "q1w2e3r4t5y6" not in out
    assert "notes/status.md:2" in out


def test_a_failed_command_with_a_secret_is_not_stored_or_echoed(mem, capsys, monkeypatch):
    start = {"session_id": "s", "source": "startup"}
    hook(capsys, monkeypatch, "session-start", start)
    outs = [hook(capsys, monkeypatch, "post-tool", failed(CURL)) for _ in range(3)]
    stop = hook(capsys, monkeypatch, "stop", {"session_id": "s"})
    assert BEARER not in "".join(outs) + stop
    assert BEARER not in every_file(mem)
    assert "The same command failed 3 times" in "".join(outs) + stop


def test_a_failed_command_with_a_real_value_is_not_stored(repo, mem, capsys, monkeypatch):
    (repo / ".env").write_text("DB_PASSWORD=dragonflies\n")
    start = {"session_id": "s", "source": "startup"}
    hook(capsys, monkeypatch, "session-start", start)
    for _ in range(3):
        hook(capsys, monkeypatch, "post-tool", failed("connect dragonflies db"))
    assert "dragonflies" not in every_file(mem)


def test_an_ordinary_failed_command_keeps_its_text(mem, capsys, monkeypatch):
    start = {"session_id": "s", "source": "startup"}
    hook(capsys, monkeypatch, "session-start", start)
    for _ in range(2):
        hook(capsys, monkeypatch, "post-tool", failed("pytest -x"))
    assert "pytest -x" in hook(capsys, monkeypatch, "stop", {"session_id": "s"})


def test_a_stored_command_from_before_is_not_echoed(mem, capsys, monkeypatch):
    start = {"session_id": "s", "source": "startup"}
    hook(capsys, monkeypatch, "session-start", start)
    path = next((mem / ".sessions").glob("*.json"))
    state = json.loads(path.read_text())
    state["fails"] = {CURL: 3}
    path.write_text(json.dumps(state))
    assert BEARER not in hook(capsys, monkeypatch, "stop", {"session_id": "s"})


def test_check_reads_the_proposals_folder(mem, capsys):
    folder = mem / "proposals"
    folder.mkdir(exist_ok=True)
    row = {"type": "candidate", "text": NOTE_SECRET}
    (folder / "migrate-candidates.jsonl").write_text(json.dumps(row) + "\n")
    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert "proposals/migrate-candidates.jsonl:1" in out and "q1w2e3r4t5y6" not in out
    assert main(["check", "--strict"]) == 1


def test_migrate_leaves_a_secret_out_of_the_worklist(repo, capsys):
    old = repo / "memory-bank"
    old.mkdir()
    (old / "log.md").write_text(f"## Log\n\n- Deploy keys live in the vault.\n- {NOTE_SECRET}\n")
    assert main(["migrate", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "1 candidate(s) hold a secret" in out and "log.md:4" in out
    assert "q1w2e3r4t5y6" not in out
    work = repo.parent / f"{repo.name}.memory" / "proposals" / "migrate-candidates.jsonl"
    text = work.read_text()
    assert "q1w2e3r4t5y6" not in text
    assert "vault" in text


def test_purge_removes_the_text_from_the_tidy_task_at_once(mem, capsys):
    text = "The staging database lives in the east region and it serves all the reads today"
    near = text.replace("today", "now")
    write_facts(
        mem,
        [
            make_fact("f-20261001-aaaa", text=text),
            make_fact("f-20261001-bbbb", text=near),
        ],
    )
    assert main(["add", f"{near} again", *ADD]) == 0
    task = mem / "proposals" / "tidy-followups.md"
    assert "east region" in task.read_text()
    capsys.readouterr()
    for fact_id in ("f-20261001-aaaa", "f-20261001-bbbb"):
        assert main(["purge", fact_id, "--reason", "secret", "--yes"]) == 0
    assert "f-20261001-aaaa" not in (task.read_text() if task.exists() else "")


def test_the_area_is_scanned_at_add(mem):
    assert main(["add", "plain", "--area", NOTE_SECRET, "--basis", "seen", "--source", "s:1"]) != 0
