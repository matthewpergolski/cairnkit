"""The candidate scan: deterministic lines from prose notes, with counts in and out."""

from cairnkit.candidates import kind_for, scan_text

NOTE = """\
# Decisions

Intro line.

- 2026-10-09 Use uv, not pip. Reason given.
- A bullet with no date
  that wraps onto a second line.
2026-10-10 A dated line with no bullet.
1. A numbered item

| a | b |
|---|---|
| 1 | 2 |

```
- not a candidate, inside code
```
"""


def test_scan_finds_bullets_numbers_and_dated_lines():
    found, _ = scan_text("decisions.md", NOTE)
    texts = [c.text for c in found]
    assert texts == [
        "2026-10-09 Use uv, not pip. Reason given.",
        "A bullet with no date that wraps onto a second line.",
        "2026-10-10 A dated line with no bullet.",
        "A numbered item",
    ]


def test_scan_keeps_file_line_and_heading():
    found, _ = scan_text("decisions.md", NOTE)
    first = found[0]
    assert (first.file, first.line, first.heading) == ("decisions.md", 5, "Decisions")
    assert first.happened_at == "2026-10-09"
    assert found[1].line == 6


def test_counts_in_equal_counts_out():
    _, counts = scan_text("decisions.md", NOTE)
    non_blank = [line for line in NOTE.splitlines() if line.strip()]
    assert counts.lines == len(non_blank)
    assert counts.lines == (
        counts.candidates
        + counts.continuation
        + counts.headings
        + counts.code
        + counts.table
        + counts.other
    )
    assert counts.candidates == 4 and counts.continuation == 1
    assert counts.headings == 1 and counts.code == 3 and counts.table == 3
    assert counts.other == 1  # "Intro line."


def test_front_matter_is_not_a_candidate():
    text = "---\ntitle: x\n---\n- a real bullet\n"
    found, counts = scan_text("a.md", text)
    assert [c.text for c in found] == ["a real bullet"]
    assert counts.other == 3


def test_hints_for_superseded_and_held_by():
    text = (
        "- 2026-10-09 One. (superseded 2026-10-10: the developer asked)\n"
        "- 2026-10-09 Two. (held by `docs/two.md`)\n"
    )
    found, _ = scan_text("decisions-archive.md", text)
    assert found[0].hint == "superseded" and found[0].held_by is None
    assert found[1].hint == "held_by" and found[1].held_by == "docs/two.md"


def test_long_line_is_flagged():
    found, _ = scan_text("a.md", "- " + "word " * 100 + "\n")
    assert found[0].too_long


def test_kind_comes_from_the_file_name_then_the_heading():
    assert kind_for("decisions.md", "Anything") == "decision"
    assert kind_for("decisions-archive.md", "") == "decision"
    assert kind_for("log.md", "") == "event"
    assert kind_for("howto/python.md", "Traps") == "trap"
    assert kind_for("howto/python.md", "What we learned") == "lesson"
    assert kind_for("status.md", "Where things stand") == "fact"


def test_tier_marks_decisions_and_traps_likely_and_the_rest_maybe():
    decisions, _ = scan_text("decisions.md", "- one\n")
    brief, _ = scan_text("brief.md", "- one\n")
    trap, _ = scan_text("howto/x.md", "## Traps\n- one\n")
    spec, _ = scan_text("specs/a.md", "## Behavior\n- one\n")
    assert [decisions[0].tier, brief[0].tier, trap[0].tier] == ["likely"] * 3
    assert spec[0].tier == "maybe"
