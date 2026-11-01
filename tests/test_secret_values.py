"""A real value from an untracked .env file, and stored facts that the scan catches later."""

from __future__ import annotations

import io
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
    ],
)
def test_load_masks_a_stored_secret_and_keeps_the_fact(mem, capsys, record):
    plant(mem, fact("f-20261001-aaaa", "Keep this fact."), record)
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "correct.horse.battery" not in out
    assert "staging login: password=[secret: assigned secret]" in out
    assert "Keep this fact." in out
    assert 'memory add "TEXT" --supersedes' in out and BAD in out
    assert "Remove it now" not in out and "no person" not in out


@pytest.mark.parametrize(
    "record",
    [
        fact(BAD, "plain words", summary=OLD_SECRET),
        fact(BAD, "plain words", source=f"note:{OLD_SECRET}"),
    ],
)
def test_each_field_of_a_stored_fact_is_masked(mem, capsys, record):
    plant(mem, record)
    assert main(["load"]) == 0
    assert main(["show", BAD]) == 0
    assert "correct.horse.battery" not in capsys.readouterr().out


def test_a_masked_rule_keeps_its_section(mem, capsys):
    owner = fact(
        BAD, f"Never deploy on Friday, the {OLD_SECRET} account", kind="rule", basis="told"
    )
    plant(mem, owner)
    assert main(["load"]) == 0
    before_frame = capsys.readouterr().out.split("Stored notes")[0]
    assert "Never deploy on Friday" in before_frame


def test_the_agent_replaces_then_purges_with_no_person(mem, capsys):
    plant(mem, fact(BAD, f"login {OLD_SECRET} for staging and more"))
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert f"memory purge {BAD}" in out and "on disk" in out
    assert main(["add", "login is in the vault for staging", "--supersedes", BAD, *ADD]) == 0
    assert main(["check"]) == 1
    assert main(["purge", BAD, "--reason", "replaced", "--yes"]) == 0
    assert "correct.horse.battery" not in stored(mem)
    capsys.readouterr()
    assert main(["load"]) == 0
    assert BAD not in capsys.readouterr().out
    assert main(["check"]) == 0


def test_a_word_from_a_env_file_is_masked_and_can_stay(repo, mem, capsys):
    plant(mem, fact(BAD, f"login uses {VALUE} on staging"))
    assert main(["load"]) == 0
    assert VALUE in capsys.readouterr().out
    (repo / ".env").write_text(f"DB_PASSWORD={VALUE}\n")
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert VALUE not in out and "login uses [secret: DB_PASSWORD] on staging" in out
    assert "leave the fact" in out
    assert main(["check"]) == 0
    out = capsys.readouterr().out
    assert VALUE not in out and f"memory purge {BAD}" in out and "on disk" in out
    assert main(["check", "--strict"]) == 1
    (repo / ".env").unlink()
    assert main(["check", "--strict"]) == 0
    assert VALUE in stored(mem)


def test_a_value_with_its_own_shape_stays_an_error(repo, mem, capsys):
    plant(mem, fact(BAD, "login uses abc123xyz789 on staging"))
    (repo / ".env").write_text("HOST_CODE=abc123xyz789\n")
    assert main(["check"]) == 1
    assert "abc123xyz789" not in capsys.readouterr().out


def test_show_search_change_and_keep_work_on_the_masked_text(mem, capsys):
    short = fact(BAD, f"staging login {OLD_SECRET} now", scope="short")
    plant(mem, fact("f-20261001-aaaa", "Other fact."), short)
    assert main(["show", BAD]) == 0
    out = capsys.readouterr().out
    assert "correct.horse.battery" not in out and "staging login" in out
    assert "--supersedes" in out and f"memory purge {BAD}" in out
    assert main(["search", "staging", "login"]) == 0
    out = capsys.readouterr().out
    assert "correct.horse.battery" not in out and "staging login" in out
    assert main(["search", "--all", "correct.horse.battery"]) == 0
    assert BAD not in capsys.readouterr().out
    assert main(["keep", BAD, "--reason", "still true"]) == 0
    assert main(["change", BAD, "--link", "related:f-20261001-aaaa", "--reason", "same"]) == 0
    assert main(["change", BAD, "--status", "wrong", "--reason", "no"]) == 0
    out = capsys.readouterr()
    assert "correct.horse.battery" not in out.out + out.err


def test_supersede_of_an_owner_rule_with_a_mask_keeps_its_force(mem, capsys):
    plant(
        mem,
        fact(BAD, f"Never deploy on Friday, the {OLD_SECRET} account", kind="rule", basis="told"),
    )
    assert main(["add", "Never deploy on Friday, the bot account", "--supersedes", BAD, *ADD]) == 0
    capsys.readouterr()
    assert main(["load"]) == 0
    before_frame = capsys.readouterr().out.split("Stored notes")[0]
    assert "the bot account" in before_frame
    assert main(["purge", BAD, "--reason", "replaced", "--yes"]) == 0
    assert "correct.horse.battery" not in stored(mem)


def test_an_agent_replaces_an_owner_rule_and_it_keeps_its_force(mem, capsys, monkeypatch):
    plant(mem, fact(BAD, f"Never deploy Friday, {OLD_SECRET} account", kind="rule", basis="told"))
    monkeypatch.setenv("CLAUDECODE", "1")
    assert main(["add", "Never deploy Friday, the bot account", "--supersedes", BAD]) == 0
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "the bot account" in capsys.readouterr().out.split("Stored notes")[0]


def test_a_branch_named_as_a_env_word_keeps_its_note(repo, mem, capsys):
    git(repo, "switch", "-qc", "release-word")
    note = fact(
        BAD,
        "a plain note for the branch",
        scope="short",
        until_branch_merged="release-word",
        writer="main",
    )
    plant(mem, note)
    (repo / ".env").write_text("API_TOKEN=release-word\n")
    assert main(["load"]) == 0
    assert "a plain note for the branch" in capsys.readouterr().out
    assert main(["check", "--strict"]) == 0


def test_supersede_keeps_pinned_and_the_kind(mem, capsys):
    plant(mem, fact(BAD, f"Trap: login {OLD_SECRET} fails", kind="trap", pinned=True))
    assert main(["add", "Trap: login fails on staging", "--supersedes", BAD, *ADD]) == 0
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "## Pinned" in out and "Trap: login fails on staging" in out


def test_purge_refuses_a_true_fact_with_no_replacement(mem, capsys):
    plant(mem, fact(BAD, f"Trap: the nightly job uses {OLD_SECRET} and fails"))
    assert main(["purge", BAD, "--reason", "cleanup", "--yes"]) != 0
    err = capsys.readouterr().err
    assert "correct.horse.battery" not in err
    assert "Trap: the nightly job" in err and "--supersedes" in err
    assert "correct.horse.battery" in stored(mem)


def test_purge_with_reason_secret_and_yes_is_the_explicit_way(mem):
    plant(mem, fact(BAD, f"Trap: the nightly job uses {OLD_SECRET} and fails"))
    assert main(["purge", BAD, "--reason", "secret"]) != 0
    assert "correct.horse.battery" in stored(mem)
    assert main(["purge", BAD, "--reason", "secret", "--yes"]) == 0
    assert "correct.horse.battery" not in stored(mem)


def test_purge_of_a_fact_that_is_only_the_secret_needs_no_replacement(mem):
    plant(mem, fact(BAD, OLD_SECRET))
    assert main(["purge", BAD, "--reason", "cleanup", "--yes"]) == 0
    assert "correct.horse.battery" not in stored(mem)


def test_each_masked_fact_blocks_a_stop_once(repo, mem, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    plant(mem, fact(BAD, f"staging login {OLD_SECRET} now"))
    assert main(["hook", "stop", "--agent", "claude"]) == 0
    assert BAD in capsys.readouterr().out
    for _ in range(2):
        monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
        assert main(["hook", "stop", "--agent", "claude"]) == 0
        assert BAD not in capsys.readouterr().out


def test_two_masked_texts_that_read_the_same_are_not_retired(mem, capsys):
    one = fact(BAD, "staging login password=hunter2hunter2 today")
    two = fact("f-20261002-cccc", "staging login password=wolverine99zz today")
    plant(mem, one, two)
    assert main(["tidy", "--auto", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Nothing to retire" in out


def test_a_similar_new_fact_does_not_print_the_stored_secret(mem, capsys):
    plant(mem, fact(BAD, f"the staging login for the deploy uses {OLD_SECRET} today"))
    assert main(["add", "the staging login for the deploy uses a vault today", *ADD]) == 0
    captured = capsys.readouterr()
    assert "correct.horse.battery" not in captured.out + captured.err


def test_a_note_line_with_a_secret_loads_masked(mem, capsys):
    notes = mem / "notes"
    notes.mkdir(exist_ok=True)
    (notes / "status.md").write_text(f"Working on staging.\nstaging login {OLD_SECRET}\n")
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "Working on staging." in out
    assert "correct.horse.battery" not in out and "staging login password=[secret:" in out
    assert main(["search", "staging"]) == 0
    out = capsys.readouterr().out
    assert "correct.horse.battery" not in out
    assert "status.md:2" in out and "staging login" in out
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
        ("ANY_THING=MixedCaseValue\n", "MixedCaseValue"),
        ("ANY_THING=a-long-plain-value-of-words\n", "a-long-plain-value-of-words"),
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
