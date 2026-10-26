"""Flagged similar pairs go to an agent task file, not to a person."""

import io
import json
import time

from conftest import make_fact, write_facts

from cairnkit.cli import main

A, B = "f-20261001-0001", "f-20261002-0002"
TEXT_A = "The cache must be warmed before the release job runs."
TEXT_B = "The cache must be warmed before the release job runs now."
TASK = "proposals/tidy-followups.md"


def pair_facts(**extra):
    return [
        make_fact(A, TEXT_A, learned_at="2026-10-01T00:00:00+00:00", **extra),
        make_fact(B, TEXT_B, learned_at="2026-10-02T00:00:00+00:00", **extra),
    ]


def run(capsys, *args):
    capsys.readouterr()
    code = main(list(args))
    return code, capsys.readouterr().out


def test_tidy_lists_open_pairs_and_writes_the_task(mem, capsys):
    write_facts(mem, pair_facts())
    code, out = run(capsys, "tidy")
    assert code == 0 and "Open similar pairs: 1" in out
    task = (mem / TASK).read_text()
    assert task.startswith("# Tidy follow-up (pending): 1 pair")
    assert A in task and B in task and TEXT_A in task and TEXT_B in task
    assert f"memory change {A} --status superseded --superseded-by {B}" in task
    assert f"memory change {B} --link related:{A}" in task
    assert "contradicts" in task and "`memory tidy`" in task and "Open similar pairs: 0" in task


def test_a_pair_that_add_flagged_is_listed(mem, capsys):
    write_facts(mem, [make_fact(A, TEXT_A)])
    base = ["--area", "x", "--basis", "seen", "--source", "session:2026-10-24"]
    assert main(["add", TEXT_B, *base]) == 0
    assert "Tidy follow-up" in (mem / TASK).read_text()  # add refreshes the task


def test_load_says_a_follow_up_is_pending(mem, capsys):
    write_facts(mem, pair_facts())
    run(capsys, "tidy")
    _, out = run(capsys, "load")
    assert "Tidy follow-up pending: 1 pairs; task: memory-bank/proposals/tidy-followups.md" in out


def test_load_is_quiet_without_a_task(mem, capsys):
    write_facts(mem, [make_fact(A, TEXT_A)])
    _, out = run(capsys, "load")
    assert "Tidy follow-up" not in out


def test_superseding_one_fact_resolves_the_pair_and_removes_the_task(mem, capsys):
    write_facts(mem, pair_facts())
    run(capsys, "tidy")
    assert main(["change", A, "--status", "superseded", "--superseded-by", B, "--reason", "r"]) == 0
    assert not (mem / TASK).exists()
    _, out = run(capsys, "load")
    assert "Tidy follow-up" not in out
    assert "Open similar pairs: 0" in run(capsys, "tidy")[1]


def test_a_related_link_marks_both_valid(mem, capsys):
    write_facts(mem, pair_facts())
    run(capsys, "tidy")
    assert main(["change", B, "--link", f"related:{A}", "--reason", "Both valid."]) == 0
    assert not (mem / TASK).exists()
    assert "Open similar pairs: 0" in run(capsys, "tidy")[1]


def test_a_contradicts_link_also_resolves_the_flag_and_both_stay(mem, capsys):
    write_facts(mem, pair_facts())
    assert main(["change", B, "--link", f"contradicts:{A}", "--reason", "Disagree."]) == 0
    assert not (mem / TASK).exists()
    assert "Open similar pairs: 0" in run(capsys, "tidy")[1]


def test_the_task_is_regenerated_the_same_way(mem, capsys):
    write_facts(mem, pair_facts())
    run(capsys, "tidy")
    first = (mem / TASK).read_bytes()
    run(capsys, "tidy")
    assert (mem / TASK).read_bytes() == first


def test_a_number_in_the_difference_is_not_a_pair(mem, capsys):
    write_facts(
        mem,
        [
            make_fact(A, "Retry the upload up to 3 times, short delay, each job"),
            make_fact(B, "Retry the upload up to 5 times, short delay, each job"),
        ],
    )
    assert "Open similar pairs: 0" in run(capsys, "tidy")[1]
    assert not (mem / TASK).exists()


def test_near_pairs_are_not_tidy_proposals_any_more(mem, capsys):
    write_facts(mem, pair_facts())
    _, out = run(capsys, "tidy")
    assert "[duplicate]" not in out


def test_an_exact_repeat_of_unprotected_facts_is_left_to_auto_tidy(mem, capsys):
    write_facts(
        mem,
        [make_fact(A, "Same words here."), make_fact(B, "same words here")],
    )
    assert "Open similar pairs: 0" in run(capsys, "tidy")[1]


def test_an_exact_repeat_that_auto_tidy_cannot_retire_is_a_pair(mem, capsys):
    write_facts(
        mem,
        [
            make_fact(A, "Always run the tests.", kind="rule"),
            make_fact(B, "always run the tests", kind="rule"),
        ],
    )
    assert "Open similar pairs: 1" in run(capsys, "tidy")[1]


def test_other_kind_or_scope_is_not_a_pair(mem, capsys):
    write_facts(
        mem,
        [make_fact(A, TEXT_A), make_fact(B, TEXT_B, kind="trap")],
    )
    assert "Open similar pairs: 0" in run(capsys, "tidy")[1]


def test_session_start_refreshes_the_task(mem, capsys, monkeypatch):
    write_facts(mem, pair_facts())
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s"})))
    capsys.readouterr()
    main(["hook", "session-start", "--agent", "claude"])
    out = capsys.readouterr().out
    assert (mem / TASK).is_file() and "Tidy follow-up pending: 1 pairs" in out


def test_the_scan_is_fast_for_many_facts(mem):
    from cairnkit.followups import refresh
    from cairnkit.memory import Memory
    from cairnkit.paths import find_project

    facts = [
        make_fact(f"f-20261001-{i:04x}", f"Topic{i} about part{i % 37} of module{i % 91} and more")
        for i in range(1, 1501)
    ]
    write_facts(mem, facts)
    memory = Memory.open(find_project(), None)
    start = time.perf_counter()
    refresh(memory)
    assert time.perf_counter() - start < 3.0
