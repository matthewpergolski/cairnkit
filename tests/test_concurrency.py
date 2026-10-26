"""Two sessions at once: one retire record, one log line, no lost use data."""

import json

from conftest import make_fact, read_jsonl, write_facts

from cairnkit import autotidy, usage
from cairnkit.autotidy import Retirement
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.state import fold

NOW = "2026-10-20T12:00:00+00:00"
A, B = "f-20261001-0001", "f-20261002-0002"


def copies():
    return [
        make_fact(A, "Deploys need a clean tree.", learned_at="2026-10-01T00:00:00+00:00"),
        make_fact(B, "deploys need a CLEAN tree!", learned_at="2026-10-02T00:00:00+00:00"),
    ]


def open_memory():
    return Memory.open(find_project(), None)


def test_the_record_id_is_the_same_for_the_same_retire():
    one = Retirement(A, "duplicate", "superseded", "Exact repeat of B.", superseded_by=B)
    two = Retirement(A, "duplicate", "superseded", "Exact repeat of B.", superseded_by=B)
    other = Retirement(B, "duplicate", "superseded", "Exact repeat of B.", superseded_by=B)
    assert (
        one.record("2026-10-20T12:00:00+00:00")["cid"]
        == two.record("2026-10-21T01:00:00+00:00")["cid"]
    )
    assert one.record("x")["cid"] != other.record("x")["cid"]


def test_fold_keeps_one_of_two_change_records_with_the_same_cid():
    change = {
        "type": "change", "id": A, "at": "2026-10-05T00:00:00+00:00", "writer": "auto-tidy",
        "status": "expired", "reason": "r", "cid": "abc",
    }  # fmt: skip
    states = fold([make_fact(A, "Fact."), change, dict(change, writer="other")])
    assert len(states[A]["history"]) == 1


def test_two_sessions_with_the_same_view_write_one_record_and_one_log_line(mem, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, copies())
    first, second = open_memory(), open_memory()  # both read the memory before either writes
    autotidy.retire(first)
    autotidy.retire(second)
    assert len(read_jsonl(mem / "facts" / "auto-tidy.jsonl")) == 1
    assert len((mem / "auto-tidy.log").read_text().splitlines()) == 1


def test_the_log_skips_a_line_that_is_already_there(mem, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, copies())
    memory = open_memory()
    found = autotidy.find(memory)
    autotidy.write_log(memory, found, NOW)
    autotidy.write_log(memory, found, NOW)
    assert len((mem / "auto-tidy.log").read_text().splitlines()) == 1


# --- the use record is append only -----------------------------------------------


def test_show_appends_one_line_per_use(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(mem, copies())
    main(["show", A])
    path = mem / ".usage" / "main.log"
    before = path.read_bytes()
    main(["show", A])
    after = path.read_bytes()
    assert after.startswith(before) and len(after.splitlines()) == 2
    stamp, fact_id = after.decode().splitlines()[0].split("\t")
    assert fact_id == A and stamp.startswith("2026-10-20")


def test_last_used_is_the_latest_time_over_all_writers(mem, monkeypatch):
    write_facts(mem, copies())
    folder = mem / ".usage"
    folder.mkdir()
    (folder / "one.log").write_text(
        f"2026-10-01T00:00:00+00:00\t{A}\n2026-10-05T00:00:00+00:00\t{A}\n"
    )
    (folder / "two.log").write_text(f"2026-10-03T00:00:00+00:00\t{A}\nnot a line\n\t\n")
    got = usage.last_used(open_memory())
    assert got[A].isoformat() == "2026-10-05T00:00:00+00:00"


def test_compaction_keeps_the_latest_line_per_fact_and_the_same_result(mem):
    write_facts(mem, copies())
    folder = mem / ".usage"
    folder.mkdir()
    lines = [f"2026-10-{d:02d}T00:00:00+00:00\t{A}\n" for d in range(1, 11)]
    lines.append(f"2026-10-02T00:00:00+00:00\t{B}\n")
    (folder / "main.log").write_text("".join(lines))
    memory = open_memory()
    before = usage.last_used(memory)
    usage.compact(memory, threshold=5)
    assert len((folder / "main.log").read_text().splitlines()) == 2
    assert usage.last_used(memory) == before


def test_compaction_leaves_a_short_file_alone(mem):
    write_facts(mem, copies())
    folder = mem / ".usage"
    folder.mkdir()
    (folder / "main.log").write_text(f"2026-10-01T00:00:00+00:00\t{A}\n" * 3)
    usage.compact(open_memory(), threshold=5)
    assert len((folder / "main.log").read_text().splitlines()) == 3


def test_session_start_compacts_a_long_use_file(mem, monkeypatch, capsys):
    import io

    write_facts(mem, copies())
    monkeypatch.setattr(usage, "COMPACT_AT", 5)
    folder = mem / ".usage"
    folder.mkdir()
    (folder / "main.log").write_text(f"2026-10-01T00:00:00+00:00\t{A}\n" * 20)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s"})))
    main(["hook", "session-start", "--agent", "claude"])
    assert len((folder / "main.log").read_text().splitlines()) == 1
