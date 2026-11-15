"""A damaged line and a bad config can hold a secret. Repair must not print or hide one."""

from __future__ import annotations

import json
import re

import pytest

from cairnkit.cli import main
from cairnkit.config import load_config

TORN = (
    '{"type":"fact","id":"f-20261101-dead","kind":"fact","text":"prod password=hunter2hunter2 more'
)
NO_ID = '{"type":"fact","text":"prod password=hunter2hunter2 and more'
TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"


def run(capsys, *args) -> tuple[int, str]:
    capsys.readouterr()
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def stored(mem) -> str:
    return "".join(path.read_text(errors="replace") for path in (mem / "facts").glob("*.jsonl"))


def tear(mem, text: str) -> None:
    with (mem / "facts" / "main.jsonl").open("a") as fh:
        fh.write(text)


@pytest.mark.parametrize("text", [TORN, NO_ID])
def test_check_names_a_torn_secret_before_and_after_repair(mem, capsys, text):
    tear(mem, text)
    code, out = run(capsys, "check")
    assert code == 1 and "hunter2" not in out and "line-" in out and "on disk" in out
    code, out = run(capsys, "repair")
    assert code == 1 and "hunter2" not in out and "line-" in out
    code, out = run(capsys, "check", "--strict")
    assert code == 1 and "hunter2" not in out and "line-" in out
    code, out = run(capsys, "load")
    assert code == 0 and "hunter2" not in out and "line-" in out


@pytest.mark.parametrize("text", [TORN, NO_ID])
def test_a_torn_secret_can_be_read_and_removed_with_no_hand_edit(mem, capsys, text):
    tear(mem, text)
    ref = re.search(r"line-[0-9a-f]+", run(capsys, "check")[1])[0]
    code, out = run(capsys, "show", ref)
    assert code == 0 and "hunter2" not in out and "prod" in out and "more" in out
    assert run(capsys, "purge", ref, "--reason", "cleanup", "--yes")[0] != 0
    assert "hunter2" in stored(mem)
    assert run(capsys, "purge", ref, "--reason", "secret")[0] != 0
    assert "hunter2" in stored(mem)
    code, out = run(capsys, "purge", ref, "--reason", "secret", "--yes")
    assert code == 0 and "hunter2" not in out
    assert "hunter2" not in stored(mem)
    assert run(capsys, "check", "--strict")[0] == 0


def test_repair_prints_no_env_value_and_no_token_cut_short(mem, repo, capsys):
    (repo / ".env").write_text("API_TOKEN=plainvalue42xyz\n")
    tear(
        mem, '{"type":"fact","id":"f-20261101-beef","kind":"fact","text":"the plainvalue42xyz here'
    )
    _, out = run(capsys, "repair")
    assert "plainvalue42xyz" not in out and "here" in out
    tear(mem, '\n{"type":"fact","id":"f-20261101-cafe","text":"the token ghp_abcdefghijklm')
    _code, out = run(capsys, "repair")
    assert "ghp_abc" not in out and "the token" in out


def test_repair_prints_no_value_of_a_record_with_an_odd_kind(mem, repo, capsys):
    (repo / ".env").write_text("API_TOKEN=plainvalue42xyz\n")
    record = {
        "type": "fact",
        "id": "f-20261101-beef",
        "kind": "odd",
        "text": "the value is plainvalue42xyz here",
        "area": "x",
        "happened_at": "2026-10-01",
        "learned_at": "2026-10-01T00:00:00+00:00",
        "source": "session:2026-10-01",
        "basis": "seen",
        "status": "active",
        "scope": "long",
        "writer": "main",
    }
    tear(mem, json.dumps(record) + "\n")
    assert "plainvalue42xyz" not in run(capsys, "check")[1]
    assert "plainvalue42xyz" not in run(capsys, "repair")[1]


def test_a_value_in_a_field_with_a_closed_set_is_not_printed(mem, capsys):
    tear(mem, json.dumps({"type": TOKEN, "id": "f-20261101-beef"}) + "\n")
    assert TOKEN not in run(capsys, "check")[1]
    assert TOKEN not in run(capsys, "repair")[1]
    tear(mem, json.dumps({"type": "change", "id": "f-20261101-beef", "status": TOKEN}) + "\n")
    assert TOKEN not in run(capsys, "check")[1]
    assert TOKEN not in run(capsys, "repair")[1]


def test_purge_refuses_a_secret_as_an_id_and_writes_nothing(mem, capsys):
    tear(mem, TORN)
    before = stored(mem)
    code, out = run(capsys, "purge", "password=hunter2hunter2", "--reason", "x", "--yes")
    assert code != 0 and "hunter2" not in out
    assert stored(mem) == before


def test_purge_refuses_a_word_that_is_no_record_id(mem, capsys):
    tear(mem, TORN)
    before = stored(mem)
    assert run(capsys, "purge", "prod", "--reason", "x", "--yes")[0] != 0
    assert stored(mem) == before


def test_purge_refuses_a_secret_as_a_reason(mem, capsys):
    tear(mem, TORN)
    before = stored(mem)
    code, out = run(capsys, "purge", "f-20261101-dead", "--reason", "password=hunter2hunter2")
    assert code != 0 and "hunter2" not in out
    assert stored(mem) == before


def test_an_old_tombstone_with_a_secret_for_an_id_has_a_route(mem, capsys):
    tomb = {
        "type": "tombstone",
        "id": "password=hunter2hunter2",
        "at": "2026-10-02T00:00:00+00:00",
        "reason": "x",
        "writer": "main",
    }
    tear(mem, json.dumps(tomb) + "\n")
    code, out = run(capsys, "check")
    assert code == 1 and "hunter2" not in out
    assert "hunter2" not in run(capsys, "show", "password=hunter2hunter2")[1]
    ref = re.search(r"line-[0-9a-f]+", out)[0]
    assert run(capsys, "purge", ref, "--reason", "secret", "--yes")[0] == 0
    assert "hunter2" not in stored(mem)
    assert run(capsys, "check", "--strict")[0] == 0


def test_purge_by_id_of_a_torn_secret_keeps_the_same_guard(mem, capsys):
    tear(mem, TORN)
    assert run(capsys, "purge", "f-20261101-dead", "--reason", "cleanup", "--yes")[0] != 0
    assert "hunter2" in stored(mem)
    assert run(capsys, "purge", "f-20261101-dead", "--reason", "secret", "--yes")[0] == 0
    assert "hunter2" not in stored(mem)


def test_a_purged_line_comes_back_as_no_problem_in_a_second_file(mem, capsys):
    (mem / "facts" / "other.jsonl").write_text(TORN)
    tear(mem, TORN)
    ref = re.search(r"line-[0-9a-f]+", run(capsys, "check")[1])[0]
    assert run(capsys, "purge", ref, "--reason", "secret", "--yes")[0] == 0
    assert "hunter2" not in stored(mem)
    assert run(capsys, "check", "--strict")[0] == 0


def test_config_repair_prints_no_value_and_keeps_none_on_disk(mem, capsys):
    (mem / "config.toml").write_text(f'auto_tidy = "report"\napi_token = "{TOKEN}"\n')
    _code, out = run(capsys, "repair")
    assert TOKEN not in out and "api_token" in out
    assert TOKEN not in (mem / "config.toml").read_text()
    assert TOKEN not in (mem / "config.toml.bad").read_text()
    assert "api_token" in (mem / "config.toml.bad").read_text()
    assert run(capsys, "check", "--strict")[0] == 0


def test_check_names_a_secret_in_an_old_bad_config_and_repair_masks_it(mem, capsys):
    (mem / "config.toml.bad").write_text(f'api_token = "{TOKEN}"\nother = 1\n')
    code, out = run(capsys, "check")
    assert code == 1 and TOKEN not in out and "config.toml.bad" in out and "memory repair" in out
    run(capsys, "repair")
    assert TOKEN not in (mem / "config.toml.bad").read_text()
    assert "other = 1" in (mem / "config.toml.bad").read_text()
    assert run(capsys, "check", "--strict")[0] == 0


def test_a_secret_in_a_setting_that_parses_is_found(mem, capsys):
    (mem / "config.toml").write_text(f'[areas]\n"src/" = "{TOKEN}"\n"docs/" = "docs"\n')
    code, out = run(capsys, "check")
    assert code == 1 and TOKEN not in out and "config.toml" in out
    code, out = run(capsys, "repair")
    assert TOKEN not in out
    assert TOKEN not in (mem / "config.toml").read_text()
    assert load_config(mem)["areas"] == {"docs/": "docs"}


@pytest.mark.parametrize("typo", ['atuo_tidy = "off"', 'auto_tidyy = "off"', 'autotidy = "report"'])
def test_repair_keeps_the_safest_state_for_a_mistyped_setting(mem, capsys, typo):
    (mem / "config.toml").write_text(typo + "\n")
    assert load_config(mem)["auto_tidy"] == "off"
    run(capsys, "repair")
    assert load_config(mem)["auto_tidy"] == "off"
    assert run(capsys, "check", "--strict")[0] == 0


def test_a_second_repair_keeps_the_first_bad_file(mem, capsys):
    (mem / "config.toml").write_text("first_typo = 1\n")
    run(capsys, "repair")
    assert (mem / "config.toml.bad").read_text() == "first_typo = 1\n"
    (mem / "config.toml").write_text("second_typo = 2\n")
    _code, out = run(capsys, "repair")
    assert (mem / "config.toml.bad").read_text() == "first_typo = 1\n"
    assert (mem / "config.toml.bad.2").read_text() == "second_typo = 2\n"
    assert "config.toml.bad.2" in out
