"""Session load: summary bullets, hygiene, discoverability."""

from datetime import UTC, datetime

from conftest import make_fact, write_facts

from cairnkit.cli import main
from cairnkit.load import changed_paths
from cairnkit.selection import areas_for_paths, pick, score_parts

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


def test_load_does_not_print_a_pinned_fact_twice(mem, capsys, monkeypatch):
    """Pinned facts stay under ## Pinned and are left out of ## Scenarios."""
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-p001",
                "Pinned cache rule for deploy.",
                area="deploy",
                tags=["cache"],
                pinned=True,
                summary="Pinned cache rule.",
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
                "Warm the cache before the cutover.",
                area="deploy",
                tags=["cache"],
                summary="Warm the cache first.",
            ),
        ],
    )
    out = load(capsys, "--budget", "200")
    assert "## Pinned" in out
    assert out.count("f-20261001-p001") == 1


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


def _same_area(n: int, area: str = "deploy") -> list[dict]:
    return [
        make_fact(f"f-20261001-{i:04x}", f"Distinct deploy detail number {i}.", area=area)
        for i in range(n)
    ]


def test_each_fact_that_loads_shows_its_text(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, _same_area(8))
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert all(f"Distinct deploy detail number {i}." in out for i in range(8))
    assert "8 fact(s) shown" in out
    assert "(no active long-term facts)" not in out


def test_the_clock_alone_removes_no_fact_from_the_load(mem, capsys, monkeypatch):
    write_facts(mem, _same_area(4))
    monkeypatch.setenv("MEMORY_NOW", NOW)
    capsys.readouterr()
    assert main(["load"]) == 0
    before = capsys.readouterr().out
    monkeypatch.setenv("MEMORY_NOW", "2036-10-01T12:00:00+00:00")
    assert main(["load"]) == 0
    after = capsys.readouterr().out
    assert all(f"Distinct deploy detail number {i}." in after for i in range(4))
    assert before.count("Distinct deploy") == after.count("Distinct deploy")


def _rank(facts, areas):
    return pick(facts, 120, datetime(2026, 10, 2, tzinfo=UTC), areas, set())


def _crowd(n: int) -> list[dict]:
    return [
        make_fact(
            f"f-20261001-{i:04x}",
            f"A long and recent fact about the busy area, number {i}, with several words.",
            area="busy",
            learned_at="2026-10-01T00:00:00+00:00",
        )
        for i in range(n)
    ]


def test_an_old_trap_keeps_its_area_place_when_no_signal_exists():
    trap = make_fact(
        "f-20200101-0001",
        "An old trap.",
        kind="trap",
        area="quiet",
        learned_at="2020-01-01T00:00:00+00:00",
    )
    assert trap["id"] in {s["id"] for s in _rank([*_crowd(20), trap], set())}


def test_a_trap_holds_its_area_place_over_newer_facts():
    trap = make_fact(
        "f-20200101-0001",
        "An old trap in the busy area.",
        kind="trap",
        area="busy",
        learned_at="2020-01-01T00:00:00+00:00",
    )
    assert trap["id"] in {s["id"] for s in _rank([*_crowd(20), trap], set())}


def test_a_signal_replaces_the_area_places():
    other = make_fact(
        "f-20200101-0001",
        "An old and rather long fact about another area, with just as many words as the rest.",
        area="quiet",
        learned_at="2020-01-01T00:00:00+00:00",
    )
    assert other["id"] not in {s["id"] for s in _rank([*_crowd(20), other], {"busy"})}


def test_a_trap_in_the_changed_area_gets_a_bonus():
    trap = make_fact("f-1", "A trap.", kind="trap", area="deploy")
    plain = make_fact("f-2", "A fact.", area="deploy")
    moment = datetime(2026, 10, 2, tzinfo=UTC)
    assert score_parts(trap, moment, {"deploy"}, set())["trap"] == 2.0
    assert score_parts(trap, moment, set(), set())["trap"] == 0.0
    assert score_parts(plain, moment, {"deploy"}, set())["trap"] == 0.0


def test_areas_come_from_any_part_of_a_changed_path():
    found = areas_for_paths(["src/cairnkit/load.py", "tests/test_x.py"], {})
    assert {"cairnkit", "load", "test_x"} <= found
    assert "tests" in found  # the first folder still counts
    assert "src" in found


def test_a_fact_that_names_a_changed_file_ranks_higher():
    named = make_fact("f-1", "The load step reads the budget.", area="product")
    other = make_fact("f-2", "The update step reads the source.", area="product")
    moment = datetime(2026, 10, 2, tzinfo=UTC)
    assert score_parts(named, moment, {"load"}, set())["mention"] == 1.5
    assert score_parts(other, moment, {"load"}, set())["mention"] == 0.0


def test_uncommitted_changes_are_a_signal_on_the_default_branch(repo):
    (repo / "README.md").write_text("changed\n")
    assert changed_paths(repo, "main") == ["README.md"]
