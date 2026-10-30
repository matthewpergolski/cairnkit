"""Auto-tidy retires a near duplicate when the meaning matches, and only then."""

from __future__ import annotations

import io
import json

from conftest import make_fact, write_facts

from cairnkit.cli import main

NOW = "2026-10-20T12:00:00+00:00"
OLD = "2026-10-17T12:00:00+00:00"
A, B = "f-20261001-0001", "f-20261002-0002"


def auto(capsys):
    capsys.readouterr()
    code = main(["tidy", "--auto"])
    return code, capsys.readouterr().out


def status_of(fid):
    from cairnkit.memory import Memory
    from cairnkit.paths import find_project

    return Memory.open(find_project(), None).states[fid]


def test_near_duplicate_with_the_same_meaning_is_superseded(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(A, "The cache must be warmed before the release job runs."),
            make_fact(B, "The cache must be warmed before the release job runs now."),
        ],
    )
    code, _ = auto(capsys)
    assert code == 0
    old = status_of(A)
    assert old["status"] == "superseded"
    assert old["superseded_by"] == B
    log = (mem / "auto-tidy.log").read_text()
    assert "similar_to" in log


def test_a_near_pair_with_a_different_meaning_stays_active(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(A, "The cache must be warmed before the release job runs."),
            make_fact(B, "The cache must not be warmed before the release job runs."),
        ],
    )
    auto(capsys)
    assert status_of(A)["status"] == "active"
    assert status_of(B)["status"] == "active"


def test_a_stale_long_fact_is_not_expired_and_is_proposed(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(
                A,
                "An old unlinked fact about deploys.",
                learned_at="2026-01-01T00:00:00+00:00",
            )
        ],
    )
    auto(capsys)
    assert status_of(A)["status"] == "active"
    proposal = (mem / "proposals" / "stale-pending.md").read_text()
    assert A in proposal


def test_stop_tidies_when_the_tidy_state_is_old(repo, mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    config = mem / "config.toml"
    config.write_text(config.read_text() + '\nauto_tidy = "on"\n')
    write_facts(
        mem,
        [
            make_fact(A, "Deploys need a clean tree.", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(B, "deploys need a CLEAN tree!", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    (mem / ".auto-tidy-state.json").write_text(
        json.dumps({"last_tidy_at": OLD, "started_at": OLD, "sessions": 1})
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    capsys.readouterr()
    assert main(["hook", "stop", "--agent", "generic"]) == 0
    assert status_of(A)["status"] == "superseded"
    assert status_of(A)["superseded_by"] == B
