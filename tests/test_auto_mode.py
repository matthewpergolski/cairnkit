"""Default `auto_tidy = "auto"`: report first, then turn on by itself unless a retire was undone."""

import io
import json

from conftest import make_fact, read_jsonl, write_facts

from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project

DAY0 = "2026-10-20T12:00:00+00:00"
DAY1 = "2026-10-21T12:00:00+00:00"
DAY2 = "2026-10-22T12:00:00+00:00"
DAY8 = "2026-10-28T12:00:00+00:00"
A, B, C, D = "f-20261001-0001", "f-20261002-0002", "f-20261003-0003", "f-20261004-0004"
TASK = "proposals/tidy-followups.md"


def pair(first, second, text):
    return [
        make_fact(first, text, learned_at="2026-10-01T00:00:00+00:00"),
        make_fact(second, text.upper(), learned_at="2026-10-02T00:00:00+00:00"),
    ]


def start(capsys, monkeypatch, when):
    monkeypatch.setenv("MEMORY_NOW", when)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    return capsys.readouterr().out


def status(fid):
    return Memory.open(find_project(), None).states[fid]["status"]


def state_file(mem):
    return json.loads((mem / ".auto-tidy-state.json").read_text())


def test_the_default_mode_is_auto(mem):
    assert Memory.open(find_project(), None).config["auto_tidy"] == "auto"


def test_the_first_three_session_starts_only_report(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    outs = [start(capsys, monkeypatch, d) for d in (DAY0, DAY1, DAY2)]
    assert status(A) == "active"
    assert all("report only" in o and "turns itself on" in o for o in outs)
    assert state_file(mem)["sessions"] == 3


def test_after_three_sessions_and_seven_days_it_turns_itself_on(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    for day in (DAY0, DAY1, DAY2):
        start(capsys, monkeypatch, day)
    out = start(capsys, monkeypatch, DAY8)
    assert status(A) == "superseded"
    assert "turned itself on" in out and "retired 1 fact(s)" in out


def test_seven_days_with_two_sessions_is_not_enough(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    start(capsys, monkeypatch, DAY0)
    start(capsys, monkeypatch, DAY8)
    assert status(A) == "active"
    start(capsys, monkeypatch, DAY8)
    assert status(A) == "superseded"


def test_three_sessions_in_one_day_is_not_enough(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    for _ in range(4):
        start(capsys, monkeypatch, DAY0)
    assert status(A) == "active"


def test_once_on_it_stays_on(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    for day in (DAY0, DAY1, DAY2, DAY8):
        start(capsys, monkeypatch, day)
    write_facts(mem, pair(C, D, "Fonts load from the CDN."))
    out = start(capsys, monkeypatch, DAY8)
    assert status(C) == "superseded" and "turned itself on" not in out


def undone_retire(capsys, monkeypatch):
    """A retire by hand, then a person sets the fact back to active."""
    monkeypatch.setenv("MEMORY_NOW", DAY0)
    assert main(["tidy", "--auto"]) == 0
    assert status(A) == "superseded"
    assert main(["change", A, "--status", "active", "--reason", "Both are needed."]) == 0


def test_an_undo_keeps_it_report_only_and_the_task_names_the_rule(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    undone_retire(capsys, monkeypatch)
    write_facts(mem, pair(C, D, "Fonts load from the CDN."))
    for day in (DAY0, DAY1, DAY2, DAY8):
        out = start(capsys, monkeypatch, day)
    assert status(C) == "active"
    assert "held report only" in out
    task = (mem / TASK).read_text()
    assert "duplicate" in task and A in task and "review" in task.lower()
    assert "Tidy follow-up pending: 1 pairs, 1 items; task:" in out


def test_an_undo_after_it_turned_on_switches_it_back(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    for day in (DAY0, DAY1, DAY2, DAY8):
        start(capsys, monkeypatch, day)
    assert status(A) == "superseded"
    assert main(["change", A, "--status", "active", "--reason", "Both are needed."]) == 0
    write_facts(mem, pair(C, D, "Fonts load from the CDN."))
    out = start(capsys, monkeypatch, DAY8)
    assert status(C) == "active" and "held report only" in out
    assert state_file(mem)["on"] is False


def test_release_starts_a_new_window_and_clears_the_task(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    undone_retire(capsys, monkeypatch)
    start(capsys, monkeypatch, DAY0)
    assert "Auto-tidy review" in (mem / TASK).read_text()
    capsys.readouterr()
    assert main(["tidy", "--release"]) == 0
    assert "Auto-tidy review" not in (mem / TASK).read_text()
    assert state_file(mem)["sessions"] == 0
    write_facts(mem, pair(C, D, "Fonts load from the CDN."))
    for day in (DAY0, DAY1, DAY2):
        start(capsys, monkeypatch, day)
    assert status(C) == "active"
    start(capsys, monkeypatch, DAY8)
    assert status(C) == "superseded"


def test_a_person_ending_a_fact_is_not_an_undo(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    monkeypatch.setenv("MEMORY_NOW", DAY0)
    assert main(["change", A, "--status", "expired", "--reason", "Done."]) == 0
    assert main(["change", A, "--status", "active", "--reason", "Not done."]) == 0
    for day in (DAY0, DAY1, DAY2, DAY8):
        out = start(capsys, monkeypatch, day)
    assert "held report only" not in out
    assert "Auto-tidy review" not in (mem / TASK).read_text()  # the pair itself is a pair


def test_the_retire_record_names_the_case(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    monkeypatch.setenv("MEMORY_NOW", DAY0)
    main(["tidy", "--auto"])
    [rec] = read_jsonl(mem / "facts" / "auto-tidy.jsonl")
    assert rec["case"] == "duplicate"


def test_forced_modes_ignore_the_window(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    (mem / "config.toml").write_text('auto_tidy = "on"\n')
    start(capsys, monkeypatch, DAY0)
    assert status(A) == "superseded"


def test_forced_report_never_turns_on(mem, capsys, monkeypatch):
    write_facts(mem, pair(A, B, "Deploys need a clean tree."))
    (mem / "config.toml").write_text('auto_tidy = "report"\n')
    for day in (DAY0, DAY1, DAY2, DAY8, DAY8):
        start(capsys, monkeypatch, day)
    assert status(A) == "active"


# --- preset rules that a memory lacks go into the same task -----------------------


def test_missing_preset_rules_are_an_item_in_the_task_and_preset_add_clears_it(
    repo, capsys, monkeypatch
):
    assert main(["init", "--preset", "dev"]) == 0
    memdir = repo.parent / "proj.memory"
    path = memdir / "facts" / "default.jsonl"
    keep = [r for r in read_jsonl(path) if r.get("preset_rule") != "basic.search-first"]
    path.write_text("".join(json.dumps(r) + "\n" for r in keep))
    out = start(capsys, monkeypatch, DAY0)
    task = (memdir / TASK).read_text()
    assert "memory preset add dev" in task and "basic.search-first" in task
    assert "Tidy follow-up pending: 0 pairs, 1 items" in out
    capsys.readouterr()
    assert main(["preset", "add", "dev"]) == 0
    assert not (memdir / TASK).exists()
