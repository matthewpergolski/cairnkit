#!/usr/bin/env python3
"""Fail when a pull-request body is not the six-section STE shape.

Required headings, in order, each exactly once:

  ## TL;DR
  ## How it works
  ## Summary
  ## Files changed
  ## How to test
  ## Review

Canonical body (Option A — prevents two visible copies):

  When CURSOR_AGENT_PR_BODY_BEGIN/END markers are present, the body is the
  text between them. A single cursor.com agent footer after END is ignored.
  Markers alone do not fail. Two marker pairs, or required headings both
  inside and outside the marker block, fail as a duplicate body.

Also requires a ```mermaid fence under How it works. Fails on
"Generated with", model names/ids, and Co-authored-by / Signed-off-by
trailers in the canonical body. Bare product names (Claude, Cursor,
Codex) are fine. "Open in Cursor" / "Open in Web" fail only inside the
canonical body (footer after END is ignored).

Extra shape rules (copyable with .github/workflows/pr-standards.yml):

  - No placeholder text: Pending, TBD, TODO, "paste the body",
    "once the PR number is known"
  - How to test: exactly three lines labeled Unit: / Smoke: /
    End-to-end:, each with a command+result or "not needed, because"
  - Rough STE: prose sentences over 25 words fail (skips code fences,
    tables, and mermaid)
  - Review: at least one fixed / accepted / rejected finding, and a
    head sha (short ok). When PR_HEAD_SHA is set, the Review sha must
    match that value (full or prefix of length >= 7).

Requires Python 3.10+ (stdlib only; no third-party imports).

Usage:
  python3 scripts/check_pr_body.py [PATH]
  PR_BODY='...' python3 scripts/check_pr_body.py

Reads PATH when given, else the PR_BODY environment variable, else stdin.
Exit 0 when clean, 1 when problems are found, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REQUIRED_HEADINGS = [
    "TL;DR",
    "How it works",
    "Summary",
    "Files changed",
    "How to test",
    "Review",
]

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
_H2 = re.compile(r"^##\s+(.+?)\s*$", re.M)
_MERMAID = re.compile(r"^```mermaid\s*$", re.M | re.I)
_FENCE = re.compile(r"^```")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)

_BEGIN = re.compile(r"<!--\s*CURSOR_AGENT_PR_BODY_BEGIN\s*-->", re.I)
_END = re.compile(r"<!--\s*CURSOR_AGENT_PR_BODY_END\s*-->", re.I)

_MODEL_ID = re.compile(
    r"(?i)\b(?:"
    r"gpt-[\w.\-]+|"
    r"o[1-9](?:-[\w.\-]+)+|"
    r"claude-[\w.\-]+|"
    r"gemini-[\w.\-]+|"
    r"composer-[\w.\-]+|"
    r"grok-[\w.\-]+|"
    r"llama-[\w.\-]+|"
    r"mistral-[\w.\-]+|"
    r"codex-[\w.\-]+|"
    r"cursor-[\w.\-]+"
    r")\b"
)
_ASSET_SUFFIX = re.compile(
    r"\.(?:png|jpe?g|gif|webp|svg|ico|js|css|map|md|txt)$",
    re.I,
)

_GENERATED_WITH = re.compile(r"Generated with", re.I)
_OPEN_PHRASES = ("Open in Cursor", "Open in Web")
_TRAILER = re.compile(r"(?im)^\s*(?:Co-authored-by|Co-Authored-By|Signed-off-by|Signed-Off-By)\s*:")

# Whole-line / bullet placeholders only (not mid-sentence English).
_STANDALONE_PLACEHOLDER = re.compile(
    r"(?im)^(?:[-*]\s+)?(?:\*\*)?(Pending|TBD|TODO)(?:\*\*)?\s*[.!?]?\s*$"
)
_PLACEHOLDER_PHRASE = re.compile(r"(?i)(?:paste the body|once the PR number is known)")

_TEST_LABELS = ("Unit", "Smoke", "End-to-end")
_TEST_LINE = re.compile(
    r"^(?:[-*]\s+)?(Unit|Smoke|End-to-end)\s*:\s*(.+?)\s*$",
    re.I,
)
_NOT_NEEDED = re.compile(r"(?i)not needed,\s*because")
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)
_DISPOSITION = re.compile(r"(?i)\b(?:fixed|accepted|rejected)\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def canonical_pr_body(text: str) -> tuple[str, list[str]]:
    """Return (canonical body, packaging errors).

    Option A: text between a single BEGIN/END pair is the body. A footer
    after END is ignored. Duplicate marker pairs or required headings
    outside the pair fail.
    """
    errors: list[str] = []
    begins = list(_BEGIN.finditer(text))
    ends = list(_END.finditer(text))

    if not begins and not ends:
        return text, errors

    if len(begins) != 1 or len(ends) != 1:
        errors.append(
            "duplicate CURSOR_AGENT_PR_BODY marker wrap found. "
            "Fix: keep a single BEGIN/END pair around one six-section body."
        )
        return text, errors

    begin, end = begins[0], ends[0]
    if end.start() < begin.end():
        errors.append(
            "CURSOR_AGENT_PR_BODY markers are out of order. "
            "Fix: place BEGIN before END around one six-section body."
        )
        return text, errors

    inside = text[begin.end() : end.start()]
    outside = text[: begin.start()] + text[end.end() :]

    # Required headings outside the marker block mean a second visible copy.
    outside_titles = []
    for match in _HEADING.finditer(outside):
        title = match.group(2).strip()
        if title in REQUIRED_HEADINGS:
            outside_titles.append(title)
    if outside_titles:
        shown = ", ".join(sorted(set(outside_titles), key=REQUIRED_HEADINGS.index))
        errors.append(
            "duplicate PR body: required heading(s) appear outside the "
            f"CURSOR_AGENT marker block ({shown}). "
            "Fix: keep one six-section body inside the markers only."
        )

    return inside, errors


def _section(text: str, title: str) -> str | None:
    pattern = re.compile(rf"^##\s+{re.escape(title)}\s*$", re.M)
    match = pattern.search(text)
    if match is None:
        return None
    rest = text[match.end() :]
    stop = _H2.search(rest)
    return rest[: stop.start()] if stop else rest


def _strip_comments(text: str) -> str:
    return _HTML_COMMENT.sub("", text)


def _check_markers(text: str, errors: list[str]) -> None:
    open_hits = [phrase for phrase in _OPEN_PHRASES if phrase in text]
    if open_hits:
        shown = " / ".join(open_hits)
        errors.append(
            f"{shown} found in the canonical PR body. "
            "Fix: remove Open in Cursor / Open in Web from the six-section body "
            "(a cursor.com footer after CURSOR_AGENT_PR_BODY_END is ignored)."
        )

    if _GENERATED_WITH.search(text):
        errors.append(
            '"Generated with" attribution found. '
            'Fix: remove "Generated with ..." lines from the PR body.'
        )

    models = sorted(
        {m.group(0) for m in _MODEL_ID.finditer(text) if not _ASSET_SUFFIX.search(m.group(0))}
    )
    for model in models:
        errors.append(
            f"model id {model!r} found. "
            "Fix: remove model names/ids from the PR body; product names "
            "(Claude, Cursor, Codex) are fine."
        )

    if _TRAILER.search(text):
        errors.append(
            "AI/co-author trailer found in the PR body. "
            "Fix: remove Co-authored-by / Signed-off-by trailers from the PR body."
        )


def _check_headings(text: str, errors: list[str]) -> None:
    found: list[str] = []
    for match in _HEADING.finditer(text):
        title = match.group(2).strip()
        if title in REQUIRED_HEADINGS:
            found.append(title)

    for title in REQUIRED_HEADINGS:
        count = found.count(title)
        if count > 1:
            errors.append(
                f"heading {title!r} appears {count} times. "
                f"Fix: keep a single ## {title} section; remove the duplicate copy."
            )

    missing = [h for h in REQUIRED_HEADINGS if h not in found]
    if missing:
        errors.append(
            "missing required heading(s): "
            + ", ".join(missing)
            + ". Fix: add the six headings in order: "
            + ", ".join(REQUIRED_HEADINGS)
            + "."
        )
    elif all(found.count(h) == 1 for h in REQUIRED_HEADINGS) and found != list(REQUIRED_HEADINGS):
        errors.append(
            "required headings are out of order. "
            "Fix: use the six headings in order: " + ", ".join(REQUIRED_HEADINGS) + "."
        )


def _check_mermaid(text: str, errors: list[str]) -> None:
    how = _section(text, "How it works")
    if how is None:
        return
    if not _MERMAID.search(how):
        errors.append(
            "How it works lacks a ```mermaid fence. "
            "Fix: add a ```mermaid code fence under How it works."
        )


def _outside_fences(text: str) -> str:
    """Return text with fenced code blocks removed (same toggle as STE)."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        out.append(line)
    return "\n".join(out)


def _check_placeholders(visible: str, errors: list[str]) -> None:
    # H2: skip fences. H1: Pending/TBD/TODO only as a whole line or bullet.
    scan = _outside_fences(visible)
    words = sorted({m.group(1) for m in _STANDALONE_PLACEHOLDER.finditer(scan)})
    phrases = sorted({m.group(0) for m in _PLACEHOLDER_PHRASE.finditer(scan)})
    for item in words + phrases:
        errors.append(
            f"placeholder text {item!r} found. "
            "Fix: replace Pending/TBD/TODO and paste-later notes with real STE prose."
        )


def _test_line_ok(body: str) -> bool:
    if _NOT_NEEDED.search(body):
        return True
    # Prefer backticks, but allow a bare command plus trailing result text.
    if "`" in body:
        without_cmds = re.sub(r"`[^`]*`", " ", body).strip()
        return bool(without_cmds and re.search(r"[A-Za-z0-9]", without_cmds))
    # No backticks: need a command token and a result separator or word.
    if not re.search(r"[A-Za-z0-9]", body):
        return False
    if re.search(r"[—–-]|\bResult\b|:", body, re.I):
        # Split off a trailing result after an em/en dash or "Result".
        if re.search(r"[—–].*\S", body) or re.search(r"(?i)\bResult\b.*\S", body):
            return True
        # "cmd -q — pass" style already covered; also "cmd — pass"
        return bool(re.search(r"[—–]\s*\S", body))
    return False


def _check_how_to_test(text: str, errors: list[str]) -> None:
    section = _section(text, "How to test")
    if section is None:
        return
    visible = _strip_comments(section)
    lines = [ln.strip() for ln in visible.splitlines() if ln.strip()]
    parsed: list[tuple[str, str]] = []
    for line in lines:
        match = _TEST_LINE.match(line)
        if match is None:
            errors.append(
                "How to test has a non-labeled line. "
                "Fix: keep exactly three lines: Unit: / Smoke: / End-to-end:."
            )
            return
        parsed.append((match.group(1), match.group(2)))

    norm = []
    for label, _ in parsed:
        low = label.casefold()
        if low == "unit":
            norm.append("Unit")
        elif low == "smoke":
            norm.append("Smoke")
        else:
            norm.append("End-to-end")

    expected = list(_TEST_LABELS)
    if norm != expected:
        errors.append(
            "How to test must be exactly three lines Unit:/Smoke:/End-to-end: "
            f"(found {norm!r}). "
            "Fix: use those three labels in order, one line each."
        )
        return

    for label, body in zip(norm, (b for _, b in parsed), strict=True):
        if not _test_line_ok(body):
            errors.append(
                f"How to test {label} line needs a command+result or "
                "'not needed, because'. "
                f"Fix: rewrite the {label} line with a command and result, "
                "or 'not needed, because …'."
            )


def _prose_regions(text: str) -> str:
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        stripped = line.strip()
        if stripped.startswith("|"):
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith(("- ", "* ")):
            continue
        if _TEST_LINE.match(stripped):
            continue
        out.append(line)
    return "\n".join(out)


def _check_ste(visible: str, errors: list[str]) -> None:
    prose = _prose_regions(visible)
    blob = re.sub(r"\s+", " ", prose).strip()
    if not blob:
        return
    for sentence in _SENTENCE_SPLIT.split(blob):
        sentence = sentence.strip()
        if not sentence:
            continue
        words = sentence.split()
        if len(words) > 25:
            preview = " ".join(words[:12]) + "…"
            errors.append(
                f"prose sentence has {len(words)} words (limit 25): {preview!r}. "
                "Fix: split into shorter STE sentences (about 25 words or fewer)."
            )


def _check_review(text: str, errors: list[str]) -> None:
    section = _section(text, "Review")
    if section is None:
        return
    visible = _strip_comments(section)
    if not _DISPOSITION.search(visible):
        errors.append(
            "Review has no fixed/accepted/rejected findings. "
            "Fix: record findings as fixed, accepted, or rejected."
        )

    # Prefer an explicit Head/sha label so words like "defaced" do not count.
    labeled = re.findall(
        r"(?i)\b(?:Head|sha)\s*[:#]?\s*([0-9a-f]{7,40})\b",
        visible,
    )
    shas = labeled or _SHA.findall(visible)
    if not labeled:
        # Without a Head:/sha label, only accept when PR_HEAD_SHA is set and matches.
        if not (os.environ.get("PR_HEAD_SHA") or os.environ.get("HEAD_SHA")):
            errors.append(
                "Review does not name the current head sha. "
                "Fix: add a Head: <sha> line in Review (short form is ok)."
            )
            return
        shas = _SHA.findall(visible)
    if not shas:
        errors.append(
            "Review does not name the current head sha. "
            "Fix: name the head sha in Review (short form is ok)."
        )
        return

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


def check_body(text: str) -> list[str]:
    """Return problem lines for one PR body (empty when clean)."""
    canonical, errors = canonical_pr_body(text)
    # Packaging errors still allow shape checks on the best-effort body.
    _check_markers(canonical, errors)
    _check_headings(canonical, errors)
    _check_mermaid(canonical, errors)

    visible = _strip_comments(canonical)
    _check_placeholders(visible, errors)
    _check_how_to_test(canonical, errors)
    _check_ste(visible, errors)
    _check_review(canonical, errors)
    return errors


def _read_body(path: str | None) -> str:
    if path is not None:
        return Path(path).read_text(encoding="utf-8")
    env = os.environ.get("PR_BODY")
    if env is not None:
        return env
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("usage: check_pr_body.py [PATH]  (or set PR_BODY, or pipe stdin)")


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
        print(f"pr-body: could not read input: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    problems = check_body(body)
    if not problems:
        print("pr-body: ok")
        return 0
    print(f"pr-body: {len(problems)} problem(s)", file=sys.stderr)
    for line in problems:
        print(f"error: {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
