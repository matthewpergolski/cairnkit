"""A real value from an untracked .env file, and stored facts that the scan catches later."""

from __future__ import annotations

import json
import os

import pytest
from conftest import git

from cairnkit.cli import main
from cairnkit.envsecrets import read_env_values
from cairnkit.paths import find_project

VALUE = "dragonflies"
ADD = ["--area", "x", "--basis", "seen", "--source", "session:1"]


def stored(mem) -> str:
    return "".join(path.read_text() for path in (mem / "facts").glob("*.jsonl"))


def test_a_real_value_is_refused_and_never_printed(repo, mem, capsys):
    (repo / ".env").write_text(f"DB_PASSWORD={VALUE}\n")
    assert main(["add", f"login uses {VALUE} on staging", *ADD]) != 0
    captured = capsys.readouterr()
    assert "DB_PASSWORD" in captured.err and ".env" in captured.err
    assert VALUE not in captured.out + captured.err
    assert VALUE not in stored(mem)


@pytest.mark.parametrize(
    ("line", "text"),
    [
        ("NODE_ENV=production\n", "the deploy goes to production"),
        ("POSTGRES_PASSWORD=postgres\n", "the app uses postgres"),
        ("DB_PASSWORD=development\n", "run the development server"),
        ("API_KEY=changeme\n", "the example says changeme"),
        ("DB_PASSWORD=admin\n", "ask the admin"),
        ("PASSWORD_FILE=/run/keyfile\n", "see /run/keyfile for it"),
        (f"DB_PASSWORD={VALUE}\n", f"x{VALUE}2 is a package"),
        (f"# DB_PASSWORD={VALUE}\n", f"the {VALUE} team"),
    ],
)
def test_an_ordinary_value_or_word_is_not_refused(repo, mem, line, text):
    (repo / ".env").write_text(line)
    assert main(["add", text, *ADD]) == 0


def test_each_field_of_a_new_fact_is_scanned(repo, mem):
    (repo / ".env").write_text(f"DB_PASSWORD={VALUE}\n")
    base = ["--basis", "seen"]
    assert main(["add", "plain", "--area", VALUE, "--source", "s:1", *base]) != 0
    assert main(["add", "plain", "--area", "x", "--source", VALUE, *base]) != 0
    assert main(["add", "plain", "--summary", VALUE, *ADD]) != 0
    assert main(["add", "plain", "--tag", VALUE, *ADD]) != 0


def test_a_folder_outside_git_reads_its_env_file(tmp_path, monkeypatch):
    folder = tmp_path / "plain"
    folder.mkdir()
    (folder / ".env").write_text(f"DB_PASSWORD={VALUE}\n")
    assert read_env_values(find_project(folder)).find(VALUE)


@pytest.mark.parametrize(
    "line",
    [
        f'export DB_PASSWORD="{VALUE}"\n',
        f"DB_PASSWORD='{VALUE}'\n",
        f"DB_PASSWORD={VALUE} # staging\n",
        f"STRIPE_SECRET_KEY = {VALUE}\n",
        f"SSH_KEY={VALUE}\n",
    ],
)
def test_the_forms_of_a_line_in_a_env_file(repo, mem, line):
    (repo / ".env").write_text(line)
    assert main(["add", f"login uses {VALUE} on staging", *ADD]) != 0


@pytest.mark.parametrize("name", [".env.local", ".env.production", ".envrc"])
def test_each_untracked_env_file_is_read(repo, mem, name):
    (repo / name).write_text(f"DB_PASSWORD={VALUE}\n")
    assert main(["add", f"login uses {VALUE} on staging", *ADD]) != 0


def test_a_env_file_in_a_subfolder_is_read(repo, mem):
    (repo / "apps" / "web").mkdir(parents=True)
    (repo / "apps" / "web" / ".env.local").write_text(f"DB_PASSWORD={VALUE}\n")
    assert main(["add", f"login uses {VALUE} on staging", *ADD]) != 0


@pytest.mark.parametrize("name", [".env.example", ".env.sample", ".env.template"])
def test_an_example_file_is_not_read(repo, mem, name):
    (repo / name).write_text(f"DB_PASSWORD={VALUE}\n")
    assert main(["add", f"login uses {VALUE} on staging", *ADD]) == 0


def test_a_tracked_file_is_not_read(repo, mem):
    (repo / ".env").write_text(f"DB_PASSWORD={VALUE}\n")
    git(repo, "add", "-f", ".env")
    git(repo, "commit", "-qm", "env")
    assert main(["add", f"login uses {VALUE} on staging", *ADD]) == 0


def test_a_env_file_in_the_main_checkout_counts_in_a_worktree(repo, mem, tmp_path, monkeypatch):
    (repo / ".env").write_text(f"DB_PASSWORD={VALUE}\n")
    other = tmp_path / "other-worktree"
    git(repo, "worktree", "add", "-q", str(other), "-b", "other")
    monkeypatch.chdir(other)
    assert main(["add", f"login uses {VALUE} on staging", *ADD]) != 0


def test_a_bad_env_file_never_fails(repo, mem):
    (repo / ".env").mkdir()
    (repo / ".env.local").write_bytes(b"\xff\xfe\x00DB_PASSWORD\n")
    locked = repo / ".env.staging"
    locked.write_text(f"DB_PASSWORD={VALUE}\n")
    locked.chmod(0)
    os.symlink(repo / "gone", repo / ".env.broken")
    try:
        assert main(["add", "an ordinary fact", *ADD]) == 0
    finally:
        locked.chmod(0o600)


def test_the_values_do_not_show_in_a_repr(repo, mem):
    (repo / ".env").write_text(f"DB_PASSWORD={VALUE}\n")
    values = read_env_values(find_project(repo))
    assert values.find(f"it is {VALUE}.") == ["value of DB_PASSWORD in .env"]
    assert VALUE not in repr(values)


def fact(fact_id: str, text: str, **extra) -> dict:
    return {
        "type": "fact",
        "id": fact_id,
        "kind": "fact",
        "text": text,
        "area": "x",
        "happened_at": "2026-10-01",
        "learned_at": "2026-10-01T00:00:00+00:00",
        "source": "session:2026-10-01",
        "basis": "seen",
        "status": "active",
        "scope": "long",
        "writer": "main",
        **extra,
    }


BAD = "f-20261001-bbbb"
OLD_SECRET = "password=correct.horse.battery"


def plant(mem, *records: dict) -> None:
    (mem / "facts" / "main.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))


@pytest.mark.parametrize(
    "record",
    [
        fact(BAD, f"staging login: {OLD_SECRET}"),
        fact(BAD, f"staging login: {OLD_SECRET}", kind="rule"),
        fact(BAD, f"staging login: {OLD_SECRET}", pinned=True),
        fact(BAD, "plain words", summary=OLD_SECRET),
        fact(BAD, "plain words", source=f"note {OLD_SECRET}"),
    ],
)
def test_load_withholds_a_stored_secret_and_names_the_purge(mem, capsys, record):
    plant(mem, fact("f-20261001-aaaa", "Keep this fact."), record)
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "correct.horse.battery" not in out
    assert BAD in out and f"memory purge {BAD}" in out
    assert "Keep this fact." in out


def test_the_agent_can_purge_it_with_no_person(mem, capsys):
    plant(mem, fact(BAD, f"login {OLD_SECRET}"))
    assert main(["check"]) == 1
    assert f"memory purge {BAD}" in capsys.readouterr().out
    assert main(["purge", BAD, "--reason", "secret", "--yes"]) == 0
    assert "correct.horse.battery" not in stored(mem)
    capsys.readouterr()
    assert main(["load"]) == 0
    assert BAD not in capsys.readouterr().out
    assert main(["check"]) == 0


def test_a_real_value_stored_before_is_withheld_by_load_and_check(repo, mem, capsys):
    plant(mem, fact(BAD, f"login uses {VALUE} on staging"))
    assert main(["load"]) == 0
    assert VALUE in capsys.readouterr().out
    (repo / ".env").write_text(f"DB_PASSWORD={VALUE}\n")
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert VALUE not in out and BAD in out and "DB_PASSWORD" in out
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert VALUE not in out and f"memory purge {BAD}" in out


def test_show_search_and_change_hold_the_text_back(mem, capsys):
    plant(mem, fact(BAD, f"staging login {OLD_SECRET}"))
    assert main(["show", BAD]) == 0
    out = capsys.readouterr().out
    assert "correct.horse.battery" not in out and f"memory purge {BAD}" in out
    assert main(["search", "staging", "login"]) == 0
    assert "correct.horse.battery" not in capsys.readouterr().out
    assert main(["search", "--all", "staging"]) == 0
    assert "correct.horse.battery" not in capsys.readouterr().out
    assert main(["change", BAD, "--status", "wrong", "--reason", "no"]) != 0
    assert f"memory purge {BAD}" in capsys.readouterr().err


def test_an_ended_fact_with_a_secret_is_named_too(mem, capsys):
    change = {
        "type": "change",
        "id": BAD,
        "at": "2026-10-02T00:00:00+00:00",
        "status": "wrong",
        "reason": "bad",
        "writer": "main",
    }
    plant(mem, fact(BAD, f"login {OLD_SECRET}"), change)
    assert main(["load"]) == 0
    assert f"memory purge {BAD}" in capsys.readouterr().out


def test_a_similar_new_fact_does_not_print_the_stored_secret(mem, capsys):
    plant(mem, fact(BAD, f"the staging login for the deploy uses {OLD_SECRET} today"))
    assert main(["add", "the staging login for the deploy uses a vault today", *ADD]) == 0
    captured = capsys.readouterr()
    assert "correct.horse.battery" not in captured.out + captured.err


def test_a_note_line_with_a_secret_is_not_loaded_or_found(mem, capsys):
    notes = mem / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "status.md").write_text(f"Working on staging.\nstaging login {OLD_SECRET}\n")
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "Working on staging." in out
    assert "correct.horse.battery" not in out and "notes/status.md" in out
    assert main(["search", "staging"]) == 0
    out = capsys.readouterr().out
    assert "correct.horse.battery" not in out
    assert "status.md:2" in out
    assert main(["check"]) == 0
    assert "status.md:2" in capsys.readouterr().out


def test_check_finds_a_real_value_in_a_note(repo, mem, capsys):
    (repo / ".env").write_text(f"DB_PASSWORD={VALUE}\n")
    notes = mem / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "todo.txt").write_text(f"login uses {VALUE}\n")
    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert "todo.txt:1" in out and "DB_PASSWORD" in out and VALUE not in out


def test_an_old_tombstone_that_holds_a_secret_can_be_purged_again(mem, capsys):
    tomb = {
        "type": "tombstone",
        "id": BAD,
        "at": "2026-10-02T00:00:00+00:00",
        "reason": f"held {OLD_SECRET}",
        "writer": "main",
    }
    plant(mem, tomb)
    assert main(["check"]) == 1
    assert f"memory purge {BAD}" in capsys.readouterr().out
    assert main(["purge", BAD, "--reason", "secret", "--yes"]) == 0
    assert "correct.horse.battery" not in stored(mem)
    assert main(["check"]) == 0


def test_a_clean_tombstone_still_cannot_be_purged_again(mem, capsys):
    plant(mem, fact(BAD, "plain words"))
    assert main(["purge", BAD, "--reason", "secret", "--yes"]) == 0
    assert main(["purge", BAD, "--reason", "secret", "--yes"]) != 0
    assert "already purged" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("line", "value"),
    [
        ("INVITE_CODE=blue-tulip-42\n", "blue-tulip-42"),
        ("HOST_CODE=abc123xyz789\n", "abc123xyz789"),
        ("WEBHOOK_SIGNING=whatever-long-value-7\n", "whatever-long-value-7"),
        ("ANY_NAME=MixedCaseValue\n", "MixedCaseValue"),
        ("ANY_NAME=a-long-plain-value-of-words\n", "a-long-plain-value-of-words"),
        ("DATABASE_URL=postgres://app:s3cretpw99@db/app\n", "s3cretpw99"),
        ("DATABASE_URL=postgres://app:pa%24%24word99@db/app\n", "pa$$word99"),
        ("DATABASE_URL=postgres://app:pa%24%24word99@db/app\n", "pa%24%24word99"),
    ],
)
def test_a_value_counts_by_its_own_shape_under_any_name(repo, mem, capsys, line, value):
    (repo / ".env").write_text(line)
    assert main(["add", f"the login is {value} today", *ADD]) != 0
    assert value not in capsys.readouterr().err
    assert value not in stored(mem)


@pytest.mark.parametrize(
    ("line", "text"),
    [
        ("NODE_ENV=production\n", "deploy to production"),
        ("PORT=3000\n", "listen on port 3000"),
        ("AWS_REGION=us-east-1\n", "we run in us-east-1"),
        ("REGION=us-east-1\n", "we run in us-east-1"),
        ("APP_VERSION=1.22.3\n", "pinned to 1.22.3"),
        ("MAX_UPLOAD=10485760\n", "the limit is 10485760 bytes"),
        ('GREETING="Hello 2 you all"\n', "the page says Hello 2 you all"),
        ("INVITE_CODE=welcome\n", "the welcome page"),
        ("ALGO_NAME=sha256\n", "we hash with sha256"),
        ("DATABASE_URL=postgres://postgres:postgres@localhost/app\n", "the app uses postgres"),
        ("DATABASE_URL=postgres://localhost/app\n", "the app uses postgres on localhost"),
    ],
)
def test_an_ordinary_value_under_any_name_stays_clean(repo, mem, line, text):
    (repo / ".env").write_text(line)
    assert main(["add", text, *ADD]) == 0
