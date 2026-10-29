"""scripts/check_review_gate.py: Review must leave Pending and close Blocker/High."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_review_gate.py"


def load_mod():
    spec = importlib.util.spec_from_file_location("check_review_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return load_mod()


def body_with_review(review: str) -> str:
    return f"""## TL;DR

Ship the change.

## How it works

```mermaid
flowchart LR
  A --> B
```

## Summary

Done.

## Files changed

| Purpose | Files |
| --- | --- |
| x | y |

## How to test

- Unit: pass

## Review

{review}
"""


def test_pending_fails(mod):
    for review in ("Pending", "- Pending", "PENDING", "<!-- note -->\n\nPending\n"):
        errors = mod.check_review(body_with_review(review))
        assert errors, repr(review)
        assert any("Pending" in e for e in errors)


def test_empty_review_after_comments_fails(mod):
    errors = mod.check_review(
        body_with_review("<!-- Findings as fixed / accepted / rejected. -->\n")
    )
    assert errors
    assert any("Pending" in e or "empty" in e.lower() for e in errors)


def test_missing_review_heading_fails(mod):
    text = body_with_review("none").replace("## Review\n", "## Notes\n")
    errors = mod.check_review(text)
    assert any("missing" in e.lower() and "Review" in e for e in errors)


def test_no_findings_passes(mod):
    for review in (
        "- none yet",
        "- No prior review findings on this branch yet.",
        "- Independent review found nothing to change.",
    ):
        assert mod.check_review(body_with_review(review)) == [], review


def test_fixed_and_rejected_blocker_high_pass(mod):
    review = """
- **Blocker:** hung install path — fixed in head
- **High (H1):** race on checkout — rejected (won't fix; documented)
- **Medium:** wording — accepted
"""
    assert mod.check_review(body_with_review(review)) == []


def test_open_blocker_or_high_fails(mod):
    for review in (
        "- **Blocker:** hangs forever",
        "- **High:** missing bound",
        "- High: still open",
        "- Blocker (B1): no timeout",
        "- **H1**: race without disposition",
        "- B2 still open on the install path",
    ):
        errors = mod.check_review(body_with_review(review))
        assert errors, repr(review)
        assert any("Blocker/High" in e or "fixed/rejected" in e for e in errors)


def test_accepted_alone_does_not_clear_blocker_or_high(mod):
    review = "- **High:** leftover partial — accepted"
    errors = mod.check_review(body_with_review(review))
    assert errors
    assert any("fixed/rejected" in e for e in errors)


def test_counts_line_and_not_a_blocker_are_ignored(mod):
    review = """
**Counts:** Blocker 0 · High 0 · Medium 1 · Low 0

- One **Medium**: leftover note. Not a Blocker for this change.
- **Accepted:** keep the Medium as-is.
"""
    assert mod.check_review(body_with_review(review)) == []


def test_fixed_prefix_line_that_mentions_high_passes(mod):
    review = "- **Fixed:** prior High about the race on checkout."
    assert mod.check_review(body_with_review(review)) == []


def test_cli_exits_1_on_pending(tmp_path):
    path = tmp_path / "body.md"
    path.write_text(body_with_review("Pending"), encoding="utf-8")
    result = subprocess.run(
        ["python3", str(SCRIPT), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "review-gate:" in result.stderr
    assert "Pending" in result.stderr


def test_cli_exits_0_when_clean(tmp_path):
    path = tmp_path / "body.md"
    path.write_text(
        body_with_review("- **Fixed:** XDG leak on ubuntu.\n"),
        encoding="utf-8",
    )
    result = subprocess.run(
        ["python3", str(SCRIPT), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "review-gate: ok" in result.stdout


def test_pull_request_template_is_pending_for_the_gate(mod):
    """The skeleton Review is intentionally not merge-ready until filled in."""
    template = ROOT / ".github" / "pull_request_template.md"
    errors = mod.check_review(template.read_text(encoding="utf-8"))
    assert errors
    assert any("Pending" in e or "empty" in e.lower() for e in errors)
