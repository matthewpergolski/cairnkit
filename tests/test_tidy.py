import re

from conftest import make_fact, read_jsonl, write_facts

from cairnkit.cli import main

NOW = "2026-10-20T12:00:00+00:00"


def tidy(capsys, *args):
    capsys.readouterr()
    code = main(["tidy", *args])
    return code, capsys.readouterr().out


def ids(out):
    return re.findall(r"\bp-[0-9a-f]{6}\b", out)


def change(fid, **extra):
    return {
        "type": "change",
        "id": fid,
        "at": "2026-10-05T00:00:00+00:00",
        "writer": "main",
        **extra,
    }


def test_exact_and_near_duplicates(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0001",
                "Deploys need a clean tree.",
                learned_at="2026-10-01T00:00:00+00:00",
            ),
            make_fact(
                "f-20261002-0002",
                "Deploys need a clean tree",
                learned_at="2026-10-02T00:00:00+00:00",
            ),
            make_fact(
                "f-20261003-0003",
                "The cache must be warmed before the release job runs.",
                learned_at="2026-10-03T00:00:00+00:00",
            ),
            make_fact(
                "f-20261004-0004",
                "The cache must be warmed before the release job runs now.",
                learned_at="2026-10-04T00:00:00+00:00",
            ),
            make_fact(
                "f-20261005-0005",
                "Something unrelated about fonts.",
                learned_at="2026-10-05T00:00:00+00:00",
            ),
        ],
    )
    code, out = tidy(capsys)
    assert code == 0
    task = (mem / "proposals" / "tidy-followups.md").read_text()
    assert "f-20261001-0001" in out and "f-20261003-0003" in task
    assert "f-20261005-0005" not in out + task
    assert len(ids(out)) == 1  # the near pair is a flagged pair, not a proposal


def test_tidy_writes_proposals_and_changes_no_fact(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [make_fact("f-20261001-0001", "Same text."), make_fact("f-20261002-0002", "Same text.")],
    )
    before = (mem / "facts" / "main.jsonl").read_bytes()
    code, out = tidy(capsys)
    assert code == 0
    report = mem / "proposals" / "2026-10-20.md"
    assert report.is_file()
    assert ids(out)[0] in report.read_text()
    assert (mem / "facts" / "main.jsonl").read_bytes() == before


def test_ids_are_stable(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [make_fact("f-20261001-0001", "Same text."), make_fact("f-20261002-0002", "Same text.")],
    )
    assert ids(tidy(capsys)[1]) == ids(tidy(capsys)[1])


def test_expired_short_fact_still_pinned(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0001",
                "Pinned note.",
                scope="short",
                pinned=True,
                expires_at="2026-10-10T00:00:00+00:00",
            )
        ],
    )
    _, out = tidy(capsys)
    assert "f-20261001-0001" in out and "pinned" in out


def test_superseded_chain(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Version one."),
            make_fact("f-20261001-0002", "Version two."),
            make_fact("f-20261001-0003", "Version three."),
            change(
                "f-20261001-0001", status="superseded", superseded_by="f-20261001-0002", reason="r"
            ),
            change(
                "f-20261001-0002", status="superseded", superseded_by="f-20261001-0003", reason="r"
            ),
        ],
    )
    _, out = tidy(capsys)
    assert "chain" in out
    [pid] = ids(out)
    assert main(["tidy", "--apply", pid]) == 0
    last = read_jsonl(mem / "facts" / "tidy.jsonl")[-1]
    assert last["id"] == "f-20261001-0001" and last["superseded_by"] == "f-20261001-0003"


def test_apply_writes_only_approved_changes(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Same text.", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact("f-20261002-0002", "Same text.", learned_at="2026-10-02T00:00:00+00:00"),
            make_fact("f-20261003-0003", "Other text.", learned_at="2026-10-03T00:00:00+00:00"),
            make_fact("f-20261004-0004", "Other text.", learned_at="2026-10-04T00:00:00+00:00"),
        ],
    )
    _, out = tidy(capsys)
    found = ids(out)
    assert len(found) == 2
    dup = next(
        p
        for p in found
        if out.index(p) < out.index("f-20261002-0002") + 200
        and "uplicate" in out[out.index(p) : out.index(p) + 200]
    )
    assert main(["tidy", "--apply", dup]) == 0
    records = read_jsonl(mem / "facts" / "tidy.jsonl")
    assert len(records) == 1
    assert records[0]["id"] == "f-20261001-0001"
    assert records[0]["status"] == "superseded"
    assert records[0]["superseded_by"] == "f-20261002-0002"
    capsys.readouterr()
    assert main(["check"]) == 0


def test_apply_unknown_id_writes_nothing(mem, capsys, monkeypatch):
    monkeypatch.setenv("MEMORY_NOW", NOW)
    write_facts(
        mem,
        [make_fact("f-20261001-0001", "Same text."), make_fact("f-20261002-0002", "Same text.")],
    )
    assert main(["tidy", "--apply", "p-000000"]) == 1
    assert not (mem / "facts" / "tidy.jsonl").exists()
