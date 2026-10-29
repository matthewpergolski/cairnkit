#!/usr/bin/env python3
"""Fail when a pull-request Review section is not merge-ready.

Requires a ``## Review`` section that is not empty or ``Pending``, and that
lists no Blocker or High finding unless that same finding is marked
``fixed`` or ``rejected`` (case-insensitive). Medium/Low and dispositions
like ``accepted`` are ignored by this gate.

Usage:
  python3 scripts/check_review_gate.py [PATH]
  PR_BODY='...' python3 scripts/check_review_gate.py

Reads PATH when given, else the PR_BODY environment variable, else stdin.
Exit 0 when clean, 1 when problems are found, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_HEADING_REVIEW = re.compile(r"^##\s+Review\s*$", re.M)
_NEXT_H2 = re.compile(r"^##\s+\S", re.M)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_BULLET = re.compile(r"^[-*]\s+")
# A finding line that names Blocker / High (or B1 / H1 style ids).
# Bold labels may be ``**Blocker:**`` / ``**High:**`` (colon inside the marks).
_FINDING = re.compile(
    r"(?i)^\s*(?:[-*]\s+|#{2,6}\s+)?"
    r"(?:"
    r"\*\*(?:Blocker|High):?\*\*"
    r"|(?<![A-Za-z])(?:Blocker|High)(?![A-Za-z])"
    r"|\*\*[BH]\d+:?\*\*"
    r"|(?<![A-Za-z])[BH]\d+(?![A-Za-z0-9])"
    r")"
)
_COUNTS = re.compile(r"(?i)\bCounts\b")
_NOT_A_BLOCKER = re.compile(r"(?i)\b(?:not a|no)\s+blocker\b")
_DISPOSITION = re.compile(r"(?i)\b(?:fixed|rejected)\b")


def review_section(text: str) -> str | None:
    """Return the body under ``## Review``, or None when the heading is missing."""
    match = _HEADING_REVIEW.search(text)
    if match is None:
        return None
    rest = text[match.end() :]
    stop = _NEXT_H2.search(rest)
    return rest[: stop.start()] if stop else rest


def _substantive_lines(section: str) -> list[str]:
    cleaned = _HTML_COMMENT.sub("", section)
    lines: list[str] = []
    for raw in cleaned.splitlines():
        line = raw.strip()
        if line:
            lines.append(line)
    return lines


def _is_pending(lines: list[str]) -> bool:
    if not lines:
        return True
    if len(lines) == 1:
        only = _BULLET.sub("", lines[0]).strip()
        return only.casefold() == "pending"
    return False


def _open_severity_finding(line: str) -> bool:
    """True when *line* is a Blocker/High finding without fixed/rejected."""
    if _COUNTS.search(line) or _NOT_A_BLOCKER.search(line):
        return False
    if not _FINDING.search(line):
        return False
    return _DISPOSITION.search(line) is None


def check_review(text: str) -> list[str]:
    """Return problem lines for one PR body's Review section (empty when clean)."""
    errors: list[str] = []
    section = review_section(text)
    if section is None:
        errors.append(
            "missing ## Review section. "
            "Fix: add a ## Review heading and record findings as "
            "fixed / accepted / rejected (Blocker and High must be fixed or rejected)."
        )
        return errors

    lines = _substantive_lines(section)
    if _is_pending(lines):
        errors.append(
            "Review section is empty or Pending. "
            "Fix: after independent review, replace Pending with findings "
            "marked fixed / accepted / rejected."
        )
        return errors

    for line in lines:
        if _open_severity_finding(line):
            errors.append(
                "open Blocker/High finding not marked fixed/rejected: "
                f"{line[:120]}{'…' if len(line) > 120 else ''}. "
                "Fix: mark that finding fixed or rejected on the same line."
            )
    return errors


def _read_body(path: str | None) -> str:
    if path is not None:
        return Path(path).read_text(encoding="utf-8")
    env = os.environ.get("PR_BODY")
    if env is not None:
        return env
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("usage: check_review_gate.py [PATH]  (or set PR_BODY, or pipe stdin)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        help="PR body file (default: PR_BODY env or stdin)",
    )
    args = parser.parse_args(argv)
    try:
        body = _read_body(args.path)
    except OSError as exc:
        print(f"review-gate: could not read input: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    problems = check_review(body)
    if not problems:
        print("review-gate: ok")
        return 0
    print(f"review-gate: {len(problems)} problem(s)", file=sys.stderr)
    for line in problems:
        print(f"error: {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
