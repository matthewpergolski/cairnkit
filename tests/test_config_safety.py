"""A bad config keeps the safest behavior, and `memory check` names it."""

from __future__ import annotations

import io

import pytest
from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.config import load_config

OLD, NEW = "f-20261001-0001", "f-20261002-0002"
TEXT = "The cache must be warmed before the release job runs in staging."
PLURAL = "The cache must be warmed before the release jobs runs in staging."
BAD = [
    'auto_tidy = "off"\n[areas\n',
    'auto_tidy = "of"\n',
    "auto_tidy = 5\n",
    'auto_tidyy = "off"\n',
    'autotidy = "off"\n',
    b'auto_tidy = "off"\n# caf\xe9\n',
]


def _write(mem, text):
    path = mem / "config.toml"
    path.write_bytes(text if isinstance(text, bytes) else text.encode())


@pytest.mark.parametrize("text", BAD)
def test_a_bad_config_turns_auto_tidy_off(mem, text):
    _write(mem, text)
    assert load_config(mem)["auto_tidy"] == "off"


@pytest.mark.parametrize("text", BAD)
def test_strict_check_names_a_bad_config(mem, capsys, text):
    _write(mem, text)
    capsys.readouterr()
    assert main(["check", "--strict"]) == 1
    assert "config.toml" in capsys.readouterr().out


@pytest.mark.parametrize("text", BAD)
def test_a_session_retires_nothing_under_a_bad_config(mem, capsys, monkeypatch, text):
    write_facts(
        mem,
        [
            make_fact(OLD, TEXT, learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(NEW, PLURAL, learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    _write(mem, text)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    assert "auto-tidy" not in capsys.readouterr().out
    assert not (mem / "auto-tidy.log").exists()


@pytest.mark.parametrize(
    "text",
    [
        "skills_check = 5\n",
        'skills_auto_update = "yes"\n',
        "areas = 5\n",
        "commit_msg_guard = 5\n",
        "[commit_msg_guard]\npatterns = 5\n",
        "another_key = 5\n",
    ],
)
def test_check_names_each_other_bad_setting(mem, capsys, text):
    _write(mem, text)
    capsys.readouterr()
    assert main(["check", "--strict"]) == 1
    assert "config.toml" in capsys.readouterr().out
    assert load_config(mem)["skills_auto_update"] is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        'auto_tidy = "report"\n',
        "auto_tidy = false\nskills_check = false\n",
        'short_term_days = 14\nrules_file = "x"\n',
        '[areas]\n"src/" = "core"\n[commit_msg_guard]\npatterns = ["x"]\n',
    ],
)
def test_a_good_config_is_quiet(mem, capsys, text):
    _write(mem, text)
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0


def test_a_missing_config_uses_the_defaults(mem):
    (mem / "config.toml").unlink()
    assert load_config(mem)["auto_tidy"] == "auto"
