"""A catch in a note: no false alarm, one report per line, safe advice, no block for an old file."""

from __future__ import annotations

import io
import json
import os
import time

import pytest

from cairnkit.cli import main
from cairnkit.secretscan import find_secrets, mask

TOKEN = "Zx81Qp0vLm"
REAL_LINE = f"Old link `/?k={TOKEN}`."
LONG_AGO = time.time() - 86400


def run(capsys, *args) -> tuple[int, str]:
    capsys.readouterr()
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def hook(capsys, monkeypatch, event: str, **payload) -> tuple[int, str]:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s", **payload})))
    return run(capsys, "hook", event, "--agent", "claude")


def blocked(out: str) -> bool:
    return bool(out.strip()) and json.loads(out).get("decision") == "block"


def old_file(path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (LONG_AGO, LONG_AGO))


def old_copy(repo):
    return repo.parent / f"{repo.name}.memory-old"


@pytest.mark.parametrize(
    "line",
    [
        "open `/?k=<code>`.",
        "(`/?k=<guest_code>`) or",
        "/?k=<code>",
        "see `/?k={code}`,",
        "see `/?token=${GUEST_TOKEN}`.",
        'the link "/?key=<your key>" here',
        "use `/?token=your_token`.",
        "`/?code=guests`.",
    ],
)
def test_a_url_placeholder_with_punctuation_is_no_secret(line):
    assert find_secrets(line) == []


@pytest.mark.parametrize(
    "line",
    [REAL_LINE, f"(`/?k={TOKEN}`) or", f"/?k={TOKEN}", f'"/?token={TOKEN}".'],
)
def test_a_real_url_token_with_punctuation_is_caught_and_masked(line):
    assert "secret in URL" in find_secrets(line)
    assert TOKEN not in mask(line)


def test_a_fact_can_quote_the_link_form(mem, capsys):
    code, out = run(capsys, "add", "Guests open the link form `/?k=<code>`.", "--kind", "fact")
    assert code == 0, out
    code, out = run(capsys, "add", f"Guests open `/?k={TOKEN}`.", "--kind", "fact")
    assert code != 0 and TOKEN not in out


@pytest.mark.parametrize(
    "line",
    ["password: hunter", '"family_key": "smith"', "**password:** hunter", "token: hunter (prod)"],
)
def test_a_fact_still_refuses_a_plain_word_under_a_label(line):
    assert find_secrets(line) == ["assigned secret"]


@pytest.mark.parametrize(
    "line",
    [
        "**A bad secret:** Dahl's name in the code",
        "**Secret:** nothing here is stored",
        "secret: Dahl's name",
    ],
)
def test_prose_after_a_label_is_no_assignment(line):
    assert find_secrets(line) == []


@pytest.mark.parametrize("line", ["**password:** Xk92Qp then more", "password: Xk92's value"])
def test_a_made_up_value_stays_caught_in_prose(line):
    assert find_secrets(line) == ["assigned secret"]


@pytest.mark.parametrize(
    "line",
    ['Seed: `"family_key": "smith"`.', "password: hunter", "password is 'hunter'", "?token=hunter"],
)
def test_a_plain_word_in_a_note_is_a_note_line_and_does_not_fail_strict(repo, mem, capsys, line):
    (mem / "notes" / "brief.md").write_text(f"# Brief\n{line}\n")
    code, out = run(capsys, "check", "--strict")
    assert code == 0, out
    assert "note: 1 note line(s)" in out and "notes/brief.md:2" in out
    assert "error:" not in out


def test_a_plain_word_from_env_in_a_note_does_not_fail_strict(repo, mem, capsys):
    (repo / ".env").write_text("API_TOKEN=release-word\n")
    (mem / "notes" / "brief.md").write_text("the release-word goes here\n")
    code, out = run(capsys, "check", "--strict")
    assert code == 0 and "note: 1 note line(s)" in out and "release-word" not in out


@pytest.mark.parametrize(
    "line",
    ["password: hunter2", "password: Hunter", "password: hun-ter", 'password: "two words"'],
)
def test_a_value_with_a_mark_in_a_note_fails_strict(mem, capsys, line):
    (mem / "notes" / "brief.md").write_text(f"{line}\n")
    code, out = run(capsys, "check", "--strict")
    assert code == 1 and "notes/brief.md:1" in out


def worklist_row(text: str) -> str:
    row = {"type": "candidate", "file": "notes/brief.md", "line": 2, "heading": "", "text": text}
    return json.dumps(row) + "\n"


def test_one_line_in_three_places_is_one_problem_at_the_note(repo, mem, capsys):
    (mem / "notes" / "brief.md").write_text(f"# Brief\n- {REAL_LINE}\n")
    (old_copy(repo) / "notes").mkdir(parents=True)
    (old_copy(repo) / "notes" / "brief.md").write_text(f"# Brief\n- {REAL_LINE}\n")
    (mem / "proposals").mkdir(exist_ok=True)
    (mem / "proposals" / "migrate-candidates.jsonl").write_text(worklist_row(REAL_LINE))
    code, out = run(capsys, "check", "--strict")
    assert code == 1 and TOKEN not in out
    errors = [line for line in out.splitlines() if line.startswith("error:")]
    assert len(errors) == 1
    assert errors[0].startswith("error: notes/brief.md:2:")
    assert f"{old_copy(repo).name}/notes/brief.md:2" in errors[0]
    assert "proposals/migrate-candidates.jsonl:1" in errors[0]


def test_a_secret_only_in_the_worklist_stays_reported(mem, capsys):
    (mem / "proposals").mkdir(exist_ok=True)
    (mem / "proposals" / "migrate-candidates.jsonl").write_text(worklist_row(REAL_LINE))
    code, out = run(capsys, "check", "--strict")
    assert code == 1 and "proposals/migrate-candidates.jsonl:1" in out and TOKEN not in out


def test_a_secret_only_in_the_old_copy_stays_reported(repo, mem, capsys):
    old_file(old_copy(repo) / "brief.md", f"{REAL_LINE}\n")
    code, out = run(capsys, "check", "--strict")
    assert code == 1 and f"{old_copy(repo).name}/brief.md:1" in out


def test_the_shape_of_the_worklist_itself_is_no_catch(mem, capsys):
    (mem / "proposals").mkdir(exist_ok=True)
    row = {"type": "summary", "files": {"notes/token.md": {"lines": 123456}}, "secret": ["<code>"]}
    (mem / "proposals" / "migrate-candidates.jsonl").write_text(json.dumps(row) + "\n")
    assert run(capsys, "check", "--strict")[0] == 0


def test_the_advice_never_says_to_delete_a_line(repo, mem, capsys):
    (mem / "notes" / "brief.md").write_text(f"{REAL_LINE}\n")
    old_file(old_copy(repo) / "other.md", "CRON_SECRET=q1w2e3r4t5y6\n")
    _, out = run(capsys, "check")
    assert out.count("may be a false catch") == 2
    assert out.count("change it where it is used, then replace the value") == 2
    assert "emove" not in out


def test_migrate_does_not_say_to_delete_a_line(repo, capsys):
    (repo / "memory-bank").mkdir()
    (repo / "memory-bank" / "brief.md").write_text(f"- {REAL_LINE}\n")
    code, out = run(capsys, "migrate", "--yes", "--preset", "none")
    assert code == 0 and TOKEN not in out
    assert "brief.md:1" in out and "may be a false catch" in out and "Remove these lines" not in out


def test_each_read_of_a_note_masks_a_token_that_punctuation_follows(mem, capsys):
    (mem / "notes" / "status.md").write_text(f"# Status\n- {REAL_LINE}\n")
    assert TOKEN not in run(capsys, "load")[1]
    code, out = run(capsys, "search", "old link")
    assert code == 0 and "notes/status.md:2" in out and TOKEN not in out


def test_stop_does_not_block_for_a_file_that_this_session_did_not_write(
    repo, mem, capsys, monkeypatch
):
    old_file(mem / "notes" / "brief.md", f"{REAL_LINE}\n")
    old_file(old_copy(repo) / "other.md", "CRON_SECRET=q1w2e3r4t5y6\n")
    hook(capsys, monkeypatch, "session-start")
    assert not blocked(hook(capsys, monkeypatch, "stop")[1])

    code, out = hook(capsys, monkeypatch, "post-tool", hook_event_name="PostToolUse")
    assert code == 0 and "2 line(s)" in out and "notes/brief.md:1" in out and TOKEN not in out
    assert "memory check" in out
    assert "notes/brief.md" not in hook(capsys, monkeypatch, "post-tool")[1]

    code, out = run(capsys, "check", "--strict")
    assert code == 1 and "notes/brief.md:1" in out
    assert "notes/brief.md:1" in run(capsys, "status")[1]


def test_a_session_from_before_this_version_does_not_block(mem, capsys, monkeypatch):
    hook(capsys, monkeypatch, "session-start")
    (mem / "notes" / "brief.md").write_text(f"{REAL_LINE}\n")
    state_file = next((mem / ".sessions").glob("*.json"))
    state = json.loads(state_file.read_text())
    state.pop("clock")
    state_file.write_text(json.dumps(state))
    assert not blocked(hook(capsys, monkeypatch, "stop")[1])


def test_stop_names_a_secret_that_this_session_wrote_once(mem, capsys, monkeypatch):
    old_file(mem / "notes" / "brief.md", f"{REAL_LINE}\n")
    hook(capsys, monkeypatch, "session-start")
    (mem / "notes" / "new.md").write_text("CRON_SECRET=q1w2e3r4t5y6\n")
    out = hook(capsys, monkeypatch, "stop")[1]
    assert blocked(out)
    reason = json.loads(out)["reason"]
    assert "notes/new.md:1" in reason and "may be a false catch" in reason
    assert "notes/brief.md" not in reason and "q1w2e3r4t5y6" not in reason
    assert not blocked(hook(capsys, monkeypatch, "stop")[1])


def test_stop_still_blocks_for_a_health_error(mem, capsys, monkeypatch):
    hook(capsys, monkeypatch, "session-start")
    (mem / "facts" / "main.jsonl").write_text('{"typ\n')
    assert blocked(hook(capsys, monkeypatch, "stop")[1])
