#!/usr/bin/env python3
"""Fail when a pull-request Review section is not merge-ready.

Requires a ``## Review`` section that is not empty or ``Pending``, lists no
Blocker or High finding unless marked ``fixed`` or ``rejected``, includes at
least one fixed/accepted/rejected disposition, and names the current head
sha (short ok). When ``PR_HEAD_SHA`` is set, the Review sha must match.

CURSOR_AGENT marker comments are HTML comments and are stripped. A
cursor.com footer after the marker block is ignored for Pending detection.

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
_HTML_TAG = re.compile(r"<[^>]+>", re.S)
_FOOTER_PHRASE = re.compile(r"(?i)\bopen in (?:cursor|web)\b")
_BULLET = re.compile(r"^[-*]\s+")
_FINDING = re.compile(
    r"(?i)^\s*(?:[-*]\s+|#{2,6}\s+)?"
    r"(?:"
    r"\*\*(?:Blocker|High):?\*\*"
    r"|(?:Blocker|High)(?:\s*\([^)]*\))?:"
    r"|\*\*[BH]\d+:?\*\*"
    r"|(?<![A-Za-z])[BH]\d+(?![A-Za-z0-9])"
    r")"
)
_COUNTS = re.compile(r"(?i)\bCounts\b")
_NOT_A_BLOCKER = re.compile(r"(?i)\b(?:not a|no)\s+blocker\b")
_DISPOSITION_CLOSE = re.compile(r"(?i)\b(?:fixed|rejected)\b")
_DISPOSITION_ANY = re.compile(r"(?i)\b(?:fixed|accepted|rejected)\b")
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)
_BEGIN = re.compile(r"<!--\s*CURSOR_AGENT_PR_BODY_BEGIN\s*-->", re.I)
_END = re.compile(r"<!--\s*CURSOR_AGENT_PR_BODY_END\s*-->", re.I)


def _canonical(text: str) -> tuple[str, list[str]]:
    """Prefer text between a single agent marker pair (Option A)."""
    errors: list[str] = []
    begins = list(_BEGIN.finditer(text))
    ends = list(_END.finditer(text))
    if not begins and not ends:
        return text, errors
    if len(begins) != 1 or len(ends) != 1 or ends[0].start() < begins[0].end():
        errors.append(
            "duplicate CURSOR_AGENT_PR_BODY marker wrap found. "
            "Fix: keep a single BEGIN/END pair around one six-section body."
        )
        return text, errors
    return text[begins[0].end() : ends[0].start()], errors


def review_section(text: str) -> tuple[str | None, list[str]]:
    """Return (Review body or None, packaging errors)."""
    text, packaging = _canonical(text)
    match = _HEADING_REVIEW.search(text)
    if match is None:
        return None, packaging
    rest = text[match.end() :]
    stop = _NEXT_H2.search(rest)
    return (rest[: stop.start()] if stop else rest), packaging


def _substantive_lines(section: str) -> list[str]:
    cleaned = _HTML_COMMENT.sub("", section)
    lines: list[str] = []
    for raw in cleaned.splitlines():
        line = _HTML_TAG.sub("", raw)
        line = line.replace("&nbsp;", " ").strip()
        if not line:
            continue
        without_footer = _FOOTER_PHRASE.sub("", line).strip(" \t|-")
        if not without_footer:
            continue
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
    if _COUNTS.search(line) or _NOT_A_BLOCKER.search(line):
        return False
    if not _FINDING.search(line):
        return False
    return _DISPOSITION_CLOSE.search(line) is None


def _check_head_sha(visible: str, errors: list[str]) -> None:
    labeled = re.findall(
        r"(?i)\b(?:Head|sha)\s*[:#]?\s*([0-9a-f]{7,40})\b",
        visible,
    )
    if not labeled:
        errors.append(
            "Review does not name the current head sha. "
            "Fix: add a Head: <sha> line in Review (short form is ok)."
        )
        return
    shas = labeled
    expected = os.environ.get("PR_HEAD_SHA") or os.environ.get("HEAD_SHA")
    if not expected:
        return
    expected = expected.strip().lower()
    if len(expected) < 7:
        errors.append(
            "PR_HEAD_SHA env is shorter than 7 characters. "
            "Fix: pass the full pull request head sha to the check."
        )
        return
    ok = False
    for found in shas:
        low = found.lower()
        if len(low) >= 7 and (expected.startswith(low) or low.startswith(expected)):
            ok = True
            break
    if not ok:
        errors.append(
            "Review head sha does not match PR_HEAD_SHA. "
            f"Fix: name the current head sha ({expected[:7]}…) in Review."
        )


def check_review(text: str) -> list[str]:
    """Return problem lines for one PR body's Review section (empty when clean)."""
    errors: list[str] = []
    section, packaging = review_section(text)
    errors.extend(packaging)
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

    visible = "\n".join(lines)
    if not _DISPOSITION_ANY.search(visible):
        errors.append(
            "Review has no fixed/accepted/rejected findings. "
            "Fix: record findings as fixed, accepted, or rejected."
        )

    _check_head_sha(visible, errors)

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
