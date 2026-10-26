"""The session-start hook reports by default. It retires only when `auto_tidy` is "on"."""

import io
import json

import pytest
from conftest import make_fact, read_jsonl, write_facts

from cairnkit.cli import main

NOW = "2026-10-20T12:00:00+00:00"
A, B = "f-20261001-0001", "f-20261002-0002"


def copies():
    return [
        make_fact(A, "Deploys need a clean tree.", learned_at="2026-10-01T00:00:00+00:00"),
        make_fact(B, "deploys need a CLEAN tree!", learned_at="2026-10-02T00:00:00+00:00"),
    ]


def start(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    return capsys.readouterr().out


def config(mem, line):
    (mem / "config.toml").write_text(line + "\n")


def retired(mem):
    path = mem / "facts" / "auto-tidy.jsonl"
    return read_jsonl(path) if path.exists() else []


def test_the_first_session_start_is_report_only(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, copies())
    out = start(capsys, monkeypatch)
    assert retired(mem) == []
    assert f"would retire 1: {A}" in out
    assert "report only" in out and "turns itself on" in out
    log = (mem / "auto-tidy.log").read_text()
    assert f"would retire 1: {A}" in log


def test_the_same_report_is_logged_once(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, copies())
    start(capsys, monkeypatch)
    start(capsys, monkeypatch)
    assert len((mem / "auto-tidy.log").read_text().splitlines()) == 1


def test_a_new_report_is_logged_again(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, copies())
    start(capsys, monkeypatch)
    write_facts(mem, [make_fact("f-20261003-0003", "deploys NEED a clean tree")])
    start(capsys, monkeypatch)
    assert len((mem / "auto-tidy.log").read_text().splitlines()) == 2


def test_on_retires(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    config(mem, 'auto_tidy = "on"')
    write_facts(mem, copies())
    out = start(capsys, monkeypatch)
    assert len(retired(mem)) == 1 and "retired 1 fact(s)" in out


def test_off_does_nothing_and_logs_nothing(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    config(mem, 'auto_tidy = "off"')
    write_facts(mem, copies())
    out = start(capsys, monkeypatch)
    assert retired(mem) == [] and not (mem / "auto-tidy.log").exists()
    assert "would retire" not in out


@pytest.mark.parametrize(("value", "acts"), [("true", True), ("false", False)])
def test_the_old_true_and_false_still_work(mem, capsys, monkeypatch, value, acts):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    config(mem, f"auto_tidy = {value}")
    write_facts(mem, copies())
    start(capsys, monkeypatch)
    assert bool(retired(mem)) is acts


def test_an_unknown_value_means_the_default(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    config(mem, 'auto_tidy = "sometimes"')
    write_facts(mem, copies())
    out = start(capsys, monkeypatch)
    assert retired(mem) == [] and "would retire 1" in out


def test_tidy_auto_by_hand_acts_in_report_mode(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, copies())
    capsys.readouterr()
    assert main(["tidy", "--auto"]) == 0
    assert len(retired(mem)) == 1


def test_nothing_to_report_is_silent(mem, capsys, monkeypatch):
    write_facts(mem, [make_fact(A, "One fact.")])
    out = start(capsys, monkeypatch)
    assert "would retire" not in out and not (mem / "auto-tidy.log").exists()
