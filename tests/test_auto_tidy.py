"""`memory tidy --auto`: retire the clear mechanical cases, log each one, never delete."""

import io
import json

from conftest import make_fact, read_jsonl, write_facts

from cairnkit.cli import main

NOW = "2026-10-20T12:00:00+00:00"
A, B, C = "f-20261001-0001", "f-20261002-0002", "f-20261003-0003"


def auto(capsys, *args):
    capsys.readouterr()
    code = main(["tidy", "--auto", *args])
    return code, capsys.readouterr().out


def status_of(mem, fid):
    from cairnkit.memory import Memory
    from cairnkit.paths import find_project

    return Memory.open(find_project(), None).states[fid]


def two_copies(**second):
    return [
        make_fact(A, "Deploys need a clean tree.", learned_at="2026-10-01T00:00:00+00:00"),
        make_fact(
            B, "deploys need a CLEAN tree!", learned_at="2026-10-02T00:00:00+00:00", **second
        ),
    ]


def test_exact_duplicate_is_retired_and_logged(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, two_copies())
    code, out = auto(capsys)
    assert code == 0
    old = status_of(mem, A)
    assert old["status"] == "superseded" and old["superseded_by"] == B
    assert status_of(mem, B)["status"] == "active"
    log = (mem / "auto-tidy.log").read_text()
    assert A in log and "duplicate" in log
    assert f"memory change {A} --status active" in log
    assert A in out


def test_retire_is_written_by_auto_tidy_and_is_append_only(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, two_copies())
    before = (mem / "facts" / "main.jsonl").read_bytes()
    auto(capsys)
    assert (mem / "facts" / "main.jsonl").read_bytes() == before
    [rec] = read_jsonl(mem / "facts" / "auto-tidy.jsonl")
    assert rec["type"] == "change" and rec["writer"] == "auto-tidy" and rec["reason"]


def test_second_run_does_nothing(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, two_copies())
    auto(capsys)
    size = (mem / "facts" / "auto-tidy.jsonl").read_bytes()
    log = (mem / "auto-tidy.log").read_text()
    auto(capsys)
    assert (mem / "facts" / "auto-tidy.jsonl").read_bytes() == size
    assert (mem / "auto-tidy.log").read_text() == log


def test_near_duplicate_is_not_retired(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(A, "The cache must be warmed before the release job runs."),
            make_fact(B, "The cache must be warmed before the release job runs now."),
        ],
    )
    auto(capsys)
    assert status_of(mem, A)["status"] == "active"
    assert not (mem / "facts" / "auto-tidy.jsonl").exists()


def test_different_kind_is_not_a_duplicate(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, two_copies(kind="trap"))
    auto(capsys)
    assert status_of(mem, A)["status"] == "active"


def test_status_active_undoes_a_retire_and_it_stays_undone(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, two_copies())
    auto(capsys)
    assert main(["change", A, "--status", "active", "--reason", "Both are needed."]) == 0
    assert status_of(mem, A)["status"] == "active"
    auto(capsys)
    assert status_of(mem, A)["status"] == "active"


def test_pinned_fact_is_never_retired(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    facts = two_copies()
    facts[0]["pinned"] = True
    write_facts(mem, facts)
    auto(capsys)
    assert status_of(mem, A)["status"] == "active"
    assert status_of(mem, B)["status"] == "active"


def test_a_rule_is_never_retired_even_when_repeated(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, two_copies(kind="rule"))
    auto(capsys)
    assert status_of(mem, A)["status"] == "active"
    assert not (mem / "facts" / "auto-tidy.jsonl").exists()


def test_ended_short_fact_is_retired_with_the_log_and_an_undo_hint(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(A, "Working note.", scope="short", expires_at="2026-10-10T00:00:00+00:00"),
            make_fact(B, "Later note.", scope="short", expires_at="2026-11-10T00:00:00+00:00"),
        ],
    )
    auto(capsys)
    assert status_of(mem, A)["status"] == "expired"
    assert status_of(mem, B)["status"] == "active"
    log = (mem / "auto-tidy.log").read_text()
    assert A in log and "ended" in log and f"memory keep {A}" in log


def test_short_fact_of_a_merged_branch_is_retired(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, [make_fact(A, "Note.", scope="short", until_branch_merged="gone-branch")])
    auto(capsys)
    assert status_of(mem, A)["status"] == "expired"


def test_short_fact_whose_source_file_is_gone_is_retired(repo, mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    (repo / "kept.txt").write_text("x")
    write_facts(
        mem,
        [
            make_fact(A, "Note on a file.", scope="short", source="file:old/gone.txt"),
            make_fact(B, "Note on a kept file.", scope="short", source="file:kept.txt"),
            make_fact(C, "Long fact on a gone file.", source="file:old/gone.txt"),
        ],
    )
    auto(capsys)
    assert status_of(mem, A)["status"] == "expired"
    assert "file:old/gone.txt" in (mem / "auto-tidy.log").read_text()
    assert status_of(mem, B)["status"] == "active"
    assert status_of(mem, C)["status"] == "active"


def test_source_path_outside_the_project_is_never_checked(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(A, "Note.", scope="short", source="file:/etc/hosts-nope"),
            make_fact(B, "Other.", scope="short", source="file:../outside.txt"),
        ],
    )
    auto(capsys)
    assert status_of(mem, A)["status"] == "active"
    assert status_of(mem, B)["status"] == "active"


def test_dry_run_shows_the_plan_and_writes_nothing(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, two_copies())
    code, out = auto(capsys, "--dry-run")
    assert code == 0 and A in out and "would" in out.lower()
    assert not (mem / "facts" / "auto-tidy.jsonl").exists()
    assert not (mem / "auto-tidy.log").exists()


def test_dry_run_needs_auto(mem, capsys):
    capsys.readouterr()
    assert main(["tidy", "--dry-run"]) == 1


def test_session_start_hook_retires_and_says_so(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    (mem / "config.toml").write_text('auto_tidy = "on"\n')
    write_facts(mem, two_copies())
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    out = capsys.readouterr().out
    assert status_of(mem, A)["status"] == "superseded"
    assert "auto-tidy" in out and A in out
    assert out.count(A) == 1  # the retired fact is named once and is not loaded


def test_hook_can_be_turned_off_in_config(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    (mem / "config.toml").write_text("auto_tidy = false\n")
    write_facts(mem, two_copies())
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    main(["hook", "session-start", "--agent", "claude"])
    assert status_of(mem, A)["status"] == "active"


def test_hook_never_fails_when_the_retire_step_breaks(mem, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("cairnkit.autotidy.retire", boom)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    assert "Project memory" in capsys.readouterr().out


# --- found in review ----------------------------------------------------------


def test_same_short_note_for_two_branches_is_not_a_duplicate(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    far = "2026-12-01T00:00:00+00:00"
    write_facts(
        mem,
        [
            make_fact(A, "Retry the job.", scope="short", expires_at=far, until_branch_merged="a"),
            make_fact(B, "Retry the job.", scope="short", expires_at=far, until_branch_merged="b"),
        ],
    )
    monkeypatch.setattr("cairnkit.autotidy.merged_checker", lambda root: lambda branch: False)
    auto(capsys)
    assert status_of(mem, A)["status"] == "active"


def test_log_holds_no_fact_text(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, two_copies())
    _, out = auto(capsys)
    assert "clean tree" in out
    assert "clean tree" not in (mem / "auto-tidy.log").read_text().lower()


def test_hook_note_names_at_most_ten_facts(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    (mem / "config.toml").write_text('auto_tidy = "on"\n')
    facts = [
        make_fact(
            f"f-20261001-{i:04x}",
            "Same words.",
            learned_at=f"2026-10-01T00:{i:02d}:00+00:00",
        )
        for i in range(1, 16)
    ]
    write_facts(mem, facts)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    capsys.readouterr()
    main(["hook", "session-start", "--agent", "claude"])
    out = capsys.readouterr().out
    assert "retired 14 fact(s)" in out and "and 4 more" in out
    assert "f-20261001-0001" in out and "f-20261001-000e" not in out


# --- the same words but a different count of "not" are not an exact repeat --------

TWO_NOTS = "Retry is not allowed here and not on weekends."
ONE_NOT = "Retry is not allowed here and on weekends."


def test_same_word_set_but_a_different_count_of_not_is_not_a_duplicate(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, [make_fact(A, TWO_NOTS), make_fact(B, ONE_NOT)])
    auto(capsys)
    assert status_of(mem, A)["status"] == "active"
    _, out = tidy_proposals(capsys)
    assert "[duplicate]" not in out


def test_add_does_not_supersede_a_text_with_a_different_count_of_not(mem, capsys):
    write_facts(mem, [make_fact(A, TWO_NOTS)])
    capsys.readouterr()
    base = ["--area", "x", "--basis", "seen", "--source", "session:2026-10-24"]
    assert main(["add", ONE_NOT, *base]) == 0
    assert status_of(mem, A)["status"] == "active"


def tidy_proposals(capsys):
    capsys.readouterr()
    code = main(["tidy"])
    return code, capsys.readouterr().out
