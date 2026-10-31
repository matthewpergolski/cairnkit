"""scripts/check_review_gate.py: Review must leave Pending and close Blocker/High."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_review_gate.py"
SAMPLE_SHA = "abcdef1234567890abcdef1234567890abcdef12"


def with_head(review: str, sha: str = SAMPLE_SHA) -> str:
    if "Head:" in review:
        return review
    return review.rstrip() + f"\n- Head: {sha[:7]}\n"


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


def test_pending_with_cursor_footer_still_fails(mod):
    """HTML footers must not clear a Pending Review section."""
    footer = (
        "<!-- CURSOR_AGENT_PR_BODY_END -->\n"
        '<div><a href="https://cursor.com/"><picture>'
        '<img alt="Open in Web" src="x.png"></picture></a>&nbsp;'
        '<a href="https://cursor.com/"><picture>'
        '<img alt="Open in Cursor" src="y.png"></picture></a></div>\n'
    )
    errors = mod.check_review(body_with_review(f"Pending\n\n{footer}"))
    assert errors
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


def test_no_disposition_findings_fail_without_head(mod):
    """Ready requires a real review at the current head, not a placeholder."""
    for review in (
        "- none yet",
        "- No prior review findings on this branch yet.",
        "- Independent review found nothing to change.",
    ):
        errors = mod.check_review(body_with_review(review))
        assert errors, repr(review)


def test_review_at_current_head_passes(mod, monkeypatch):
    sha = SAMPLE_SHA
    monkeypatch.setenv("PR_HEAD_SHA", sha)
    review = f"- accepted: independent review found nothing to change\n- Head: {sha[:7]}\n"
    assert mod.check_review(body_with_review(review)) == []


def test_stale_head_sha_fails_review_gate(mod, monkeypatch):
    monkeypatch.setenv("PR_HEAD_SHA", SAMPLE_SHA)
    review = "- accepted: independent review found nothing to change\n- Head: 0000000111111\n"
    errors = mod.check_review(body_with_review(review))
    assert errors
    assert any("sha" in e.lower() or "head" in e.lower() for e in errors)


def test_missing_head_sha_fails_when_env_set(mod, monkeypatch):
    monkeypatch.setenv("PR_HEAD_SHA", SAMPLE_SHA)
    review = "- accepted: independent review found nothing to change\n"
    errors = mod.check_review(body_with_review(review))
    assert errors
    assert any("sha" in e.lower() or "head" in e.lower() for e in errors)


def test_fixed_and_rejected_blocker_high_pass(mod):
    review = with_head(
        """
- **Blocker:** hung install path — fixed in head
- **High (H1):** race on checkout — rejected (won't fix; documented)
- **Medium:** wording — accepted
"""
    )
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


def test_free_prose_blocker_high_words_are_not_findings(mod):
    """M1: bare words at line start must not look like house-style findings."""
    review = with_head(
        """
- High-priority follow-up later
### High-level notes
- Blocker 0 · High 0 · Medium 1
- accepted: Independent review found nothing to change.
"""
    )
    assert mod.check_review(body_with_review(review)) == []


def test_counts_line_and_not_a_blocker_are_ignored(mod):
    review = with_head(
        """
**Counts:** Blocker 0 · High 0 · Medium 1 · Low 0

- One **Medium**: leftover note. Not a Blocker for this change.
- **Accepted:** keep the Medium as-is.
"""
    )
    assert mod.check_review(body_with_review(review)) == []


def test_fixed_prefix_line_that_mentions_high_passes(mod):
    review = with_head("- **Fixed:** prior High about the race on checkout.")
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
    sha = SAMPLE_SHA
    path = tmp_path / "body.md"
    path.write_text(
        body_with_review(f"- **Fixed:** XDG leak on ubuntu.\n- Head: {sha[:7]}\n"),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PR_HEAD_SHA"] = sha
    result = subprocess.run(
        ["python3", str(SCRIPT), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert "review-gate: ok" in result.stdout


def test_pull_request_template_is_pending_for_the_gate(mod):
    """The skeleton Review is intentionally not merge-ready until filled in."""
    template = ROOT / ".github" / "pull_request_template.md"
    errors = mod.check_review(template.read_text(encoding="utf-8"))
    assert errors
    assert any("Pending" in e or "empty" in e.lower() for e in errors)


def test_duplicate_marker_wrap_fails_review_gate(mod, monkeypatch):
    """M3: two CURSOR_AGENT wraps must fail packaging, not pass on the last Review."""
    monkeypatch.setenv("PR_HEAD_SHA", SAMPLE_SHA)
    good = body_with_review(with_head("- accepted: first wrap\n"))
    pending = body_with_review("Pending\n")
    double = (
        "<!-- CURSOR_AGENT_PR_BODY_BEGIN -->\n"
        + good
        + "<!-- CURSOR_AGENT_PR_BODY_END -->\n"
        + "<!-- CURSOR_AGENT_PR_BODY_BEGIN -->\n"
        + pending
        + "<!-- CURSOR_AGENT_PR_BODY_END -->\n"
    )
    errors = mod.check_review(double)
    assert errors
    assert any("duplicate" in e.lower() or "marker" in e.lower() for e in errors)


def test_review_gate_requires_explicit_head_label(mod, monkeypatch):
    monkeypatch.setenv("PR_HEAD_SHA", SAMPLE_SHA)
    review = f"- accepted: ok\n- reviewed at {SAMPLE_SHA[:12]}\n"
    errors = mod.check_review(body_with_review(review))
    assert errors
    assert any("Head" in e or "sha" in e.lower() for e in errors)
