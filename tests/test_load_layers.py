"""Session load: summary bullets, scenario lines, hygiene, discoverability."""

from conftest import make_fact, write_facts

from cairnkit.cli import main

NOW = "2026-10-20T12:00:00+00:00"


def load(capsys, *args):
    capsys.readouterr()
    code = main(["load", *args])
    out = capsys.readouterr()
    assert code == 0
    return out.out + out.err


def test_load_uses_summary_not_full_body(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    body = (
        "Cache keys must include the lockfile. A key built from the package name "
        "alone serves a stale wheel after a lockfile bump."
    )
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0001",
                body,
                summary="Cache keys include the lockfile.",
                area="deploy",
                tags=["cache"],
            )
        ],
    )
    out = load(capsys, "--budget", "40")
    assert "Cache keys include the lockfile." in out
    assert "stale wheel" not in out


def test_load_prints_scenario_with_source_fact_ids(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0001",
                "Cache keys include the lockfile.",
                area="deploy",
                tags=["cache"],
                summary="Cache keys include the lockfile.",
            ),
            make_fact(
                "f-20261001-0002",
                "Bake serves both cache keys for one hour.",
                area="deploy",
                tags=["cache"],
                summary="Bake serves both cache keys briefly.",
            ),
            make_fact(
                "f-20261001-0003",
                "Invoices are immutable once sent.",
                area="billing",
            ),
        ],
    )
    out = load(capsys, "--budget", "200")
    assert "## Scenarios" in out
    assert "f-20261001-0001" in out and "f-20261001-0002" in out
    assert "deploy" in out.lower() or "cache" in out.lower()


def test_load_footer_names_show_pinned_link_and_tidy(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, [make_fact("f-20261001-0001", "One fact.")])
    out = load(capsys)
    assert "memory show" in out
    assert "--pinned" in out
    assert "--link" in out
    assert "memory tidy" in out


def test_load_hygiene_line_flags_stale_and_suggests_tidy(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(
                "f-20260101-0001",
                "Very old unlinked fact.",
                learned_at="2026-01-01T00:00:00+00:00",
            ),
            make_fact(
                "f-20261001-0002",
                "Missing file source.",
                source="file:does-not-exist-anywhere.py",
                learned_at="2026-10-01T00:00:00+00:00",
            ),
        ],
    )
    out = load(capsys)
    assert "tidy" in out.lower()
    assert "stale" in out.lower() or "older" in out.lower() or "missing" in out.lower()


def test_session_start_mentions_discoverability(mem, capsys, monkeypatch):
    write_facts(mem, [make_fact("f-20261001-0001", "Alive.")])
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("{}"))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    out = capsys.readouterr().out
    assert "memory show" in out
    assert "--pinned" in out
    assert "memory tidy" in out
