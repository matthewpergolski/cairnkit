"""Body caps and the optional load summary."""

import json

from conftest import read_jsonl

from cairnkit import schema
from cairnkit.candidates import scan_text
from cairnkit.cli import main
from cairnkit.schema import validate_record

BASE = ["--area", "deploy", "--basis", "seen", "--source", "commit:abc1234"]

GOOD = {
    "type": "fact",
    "id": "f-20261001-aaaa",
    "kind": "fact",
    "text": "A good fact.",
    "area": "x",
    "happened_at": "2026-10-01",
    "learned_at": "2026-10-01T00:00:00+00:00",
    "source": "session:2026-10-01",
    "basis": "seen",
    "status": "active",
    "writer": "main",
}


def test_non_rule_body_allows_2000_and_refuses_2001():
    assert getattr(schema, "MAX_TEXT", None) == 2000
    assert getattr(schema, "RULE_MAX_TEXT", None) == 400
    assert validate_record({**GOOD, "text": "x" * 2000}) == []
    errors = validate_record({**GOOD, "text": "x" * 2001})
    assert errors and "2001" in errors[0] and "2000" in errors[0]


def test_summary_is_optional_and_capped():
    assert getattr(schema, "MAX_SUMMARY", None) == 200
    assert validate_record(GOOD) == []
    assert validate_record({**GOOD, "summary": "y" * 200}) == []
    errors = validate_record({**GOOD, "summary": "y" * 201})
    assert errors and "201" in errors[0] and "200" in errors[0]
    assert validate_record({**GOOD, "summary": "  padded"})
    assert validate_record({**GOOD, "summary": ""})


def test_a_rule_stays_at_400_and_has_no_summary():
    assert validate_record({**GOOD, "kind": "rule", "text": "r" * 400}) == []
    errors = validate_record({**GOOD, "kind": "rule", "text": "r" * 401})
    assert errors and "401" in errors[0] and "400" in errors[0]
    assert validate_record({**GOOD, "kind": "rule", "summary": "No summary on a rule."})


def test_a_change_cannot_rewrite_text_or_summary():
    change = {
        "type": "change",
        "id": GOOD["id"],
        "at": "2026-10-02T00:00:00+00:00",
        "writer": "main",
        "status": "wrong",
        "reason": "r",
        "text": "edited",
    }
    assert any("text" in err for err in validate_record(change))
    change = {k: v for k, v in change.items() if k != "text"}
    change["summary"] = "edited"
    assert any("summary" in err for err in validate_record(change))


def test_add_accepts_a_fact_past_400_and_still_refuses_a_long_rule(mem, capsys):
    assert main(["add", "x" * 401, *BASE]) == 0
    capsys.readouterr()
    assert main(["add", "y" * 401, "--kind", "rule", *BASE]) != 0
    assert "400" in capsys.readouterr().err


def test_add_stores_an_optional_summary_and_refuses_a_long_or_secret_one(mem, capsys):
    body = "Cache keys must include the lockfile. " + ("detail " * 40)
    capsys.readouterr()
    assert main(["add", body, "--summary", "Cache keys include the lockfile.", *BASE]) == 0
    [rec] = read_jsonl(mem / "facts" / "main.jsonl")
    assert rec["summary"] == "Cache keys include the lockfile."
    assert rec["text"] == body.strip()
    assert main(["add", "Another body.", "--summary", "s" * 201, *BASE]) != 0
    assert main(["add", "Another body.", "--summary", "password = hunter22xyz", *BASE]) != 0
    assert "secret" in capsys.readouterr().err.lower()
    lines = (mem / "facts" / "main.jsonl").read_text().splitlines()
    assert len(lines) == 1


def test_check_accepts_a_long_fact_with_a_summary(mem, capsys):
    rec = {**GOOD, "text": "z" * 2000, "summary": "Short load line."}
    (mem / "facts" / "main.jsonl").write_text(json.dumps(rec) + "\n")
    capsys.readouterr()
    assert main(["check"]) == 0


def test_a_medium_candidate_is_not_too_long():
    medium, _ = scan_text("a.md", "- " + ("word " * 120) + "\n")
    huge, _ = scan_text("a.md", "- " + ("x" * 2001) + "\n")
    assert medium and medium[0].too_long is False
    assert huge and huge[0].too_long is True
