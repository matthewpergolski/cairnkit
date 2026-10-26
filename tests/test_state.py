from conftest import FIXTURES

from cairnkit.state import effective_status, fold
from cairnkit.store import read_records


def test_fold_example_statuses():
    records, errors = read_records([FIXTURES / "example-facts.jsonl"])
    assert errors == []
    facts = fold(records)
    want = {
        "f-20261003-a1b2": "active",
        "f-20261003-e5f6": "superseded",
        "f-20261003-0a1b": "active",
        "f-20261012-4e5f": "wrong",
        "f-20261015-8c9d": "expired",
        "f-20261003-1e2f": "promoted",
    }
    for fid, status in want.items():
        assert facts[fid]["status"] == status, fid
    assert facts["f-20261003-e5f6"]["superseded_by"] == "f-20261003-0a1b"
    assert len(facts["f-20261012-4e5f"]["history"]) == 1
    assert {"rel": "related", "id": "f-20261014-6a7b"} in facts["f-20261012-4e5f"]["links"]


def test_changes_apply_in_date_order_not_file_order():
    records = [
        {"type": "fact", "id": "f-1", "status": "active", "learned_at": "2026-01-01"},
        {"type": "change", "id": "f-1", "at": "2026-03-01", "status": "wrong", "reason": "b"},
        {"type": "change", "id": "f-1", "at": "2026-02-01", "status": "expired", "reason": "a"},
    ]
    assert fold(records)["f-1"]["status"] == "wrong"


def short(**extra):
    return {
        "type": "fact",
        "id": "f-1",
        "status": "active",
        "scope": "short",
        "learned_at": "2026-10-01T00:00:00+00:00",
        **extra,
    }


def test_short_fact_expires_by_date():
    fact = fold([short(expires_at="2026-10-15T00:00:00+00:00")])["f-1"]
    assert effective_status(fact, now="2026-10-10T00:00:00+00:00")[0] == "active"
    status, reason = effective_status(fact, now="2026-10-16T00:00:00+00:00")
    assert status == "expired" and "2026-10-15" in reason


def test_short_fact_expires_when_branch_merged():
    fact = fold([short(until_branch_merged="feat")])["f-1"]
    now = "2026-10-02T00:00:00+00:00"
    assert effective_status(fact, now=now, is_merged=lambda b: False)[0] == "active"
    status, reason = effective_status(fact, now=now, is_merged=lambda b: b == "feat")
    assert status == "expired" and "feat" in reason


def test_long_fact_never_expires_by_time():
    fact = fold([short(scope="long", expires_at="2026-10-02T00:00:00+00:00")])["f-1"]
    assert effective_status(fact, now="2027-01-01T00:00:00+00:00")[0] == "active"
