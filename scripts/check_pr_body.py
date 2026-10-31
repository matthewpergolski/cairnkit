#!/usr/bin/env python3
"""Fail when a pull-request body is not the six-section STE shape.

Required headings, in order, each exactly once:

  ## TL;DR
  ## How it works
  ## Summary
  ## Files changed
  ## How to test
  ## Review

Also requires a ```mermaid fence under How it works. Fails when any of
those six headings appears more than once (a duplicated template paste).
Fails on Cursor agent footer markers (CURSOR_AGENT_PR_BODY, Open in
Cursor / Open in Web), "Generated with", model names/ids, and
Co-authored-by / Signed-off-by trailers in the body. Bare product names
(Claude, Cursor, Codex) are fine.

Extra shape rules (copyable with .github/workflows/pr-standards.yml):

  - No placeholder text: Pending, TBD, TODO, "paste the body",
    "once the PR number is known"
  - How to test: exactly three lines labeled Unit: / Smoke: /
    End-to-end:, each with a command+result or "not needed, because"
  - Rough STE: prose sentences over 25 words fail (skips code fences,
    tables, and mermaid)
  - Review: at least one fixed / accepted / rejected finding, and a
    head sha (short ok). When PR_HEAD_SHA is set, the Review sha must
    match that value (full or unique prefix of length >= 7).

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

# Versioned / dotted model ids. Bare Claude / Cursor / Codex are not matched.
# Trailing file extensions are ignored so asset names are not treated as ids.
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

_PLACEHOLDER_WORD = re.compile(r"(?i)\b(?:Pending|TBD|TODO)\b")
_PLACEHOLDER_PHRASE = re.compile(r"(?i)(?:paste the body|once the PR number is known)")

_TEST_LABELS = ("Unit", "Smoke", "End-to-end")
_TEST_LINE = re.compile(
    r"^[-*]\s*(Unit|Smoke|End-to-end)\s*:\s*(.+?)\s*$",
    re.I,
)
_NOT_NEEDED = re.compile(r"(?i)not needed,\s*because")
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)
_DISPOSITION = re.compile(r"(?i)\b(?:fixed|accepted|rejected)\b")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _section(text: str, title: str) -> str | None:
    """Return the body under ``## title``, or None when missing."""
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
    if "CURSOR_AGENT_PR_BODY" in text:
        errors.append(
            "CURSOR_AGENT_PR_BODY marker found. "
            "Fix: remove CURSOR_AGENT_PR_BODY HTML comment markers and the "
            "agent footer from the PR body."
        )

    open_hits = [phrase for phrase in _OPEN_PHRASES if phrase in text]
    if open_hits:
        shown = " / ".join(open_hits)
        errors.append(
            f"{shown} footer found. "
            "Fix: remove the Open in Cursor / Open in Web agent footer "
            "from the PR body."
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


def _check_placeholders(visible: str, errors: list[str]) -> None:
    words = sorted({m.group(0) for m in _PLACEHOLDER_WORD.finditer(visible)})
    phrases = sorted({m.group(0) for m in _PLACEHOLDER_PHRASE.finditer(visible)})
    for item in words + phrases:
        errors.append(
            f"placeholder text {item!r} found. "
            "Fix: replace Pending/TBD/TODO and paste-later notes with real STE prose."
        )


def _test_line_ok(body: str) -> bool:
    if _NOT_NEEDED.search(body):
        return True
    # Command in backticks plus some result text after the label value.
    if "`" not in body:
        return False
    # After stripping one fenced command, something result-like should remain.
    without_cmds = re.sub(r"`[^`]*`", " ", body).strip()
    if not without_cmds:
        return False
    # Allow "— pass", ". Result: ...", or plain trailing result words.
    return bool(re.search(r"[A-Za-z0-9]", without_cmds))


def _check_how_to_test(text: str, errors: list[str]) -> None:
    section = _section(text, "How to test")
    if section is None:
        return
    visible = _strip_comments(section)
    lines = [ln.strip() for ln in visible.splitlines() if ln.strip()]
    # Ignore pure table separator noise; How to test should be bullets only.
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

    labels = [label for label, _ in parsed]
    expected = list(_TEST_LABELS)
    # Normalize End-to-end casing from the regex capture.
    norm = []
    for label in labels:
        low = label.casefold()
        if low == "unit":
            norm.append("Unit")
        elif low == "smoke":
            norm.append("Smoke")
        else:
            norm.append("End-to-end")

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
    """Drop fenced code and table rows so STE only sees prose."""
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
        # Structured list lines (How to test / Review) are not STE prose.
        if stripped.startswith(("- ", "* ")):
            continue
        out.append(line)
    return "\n".join(out)


def _check_ste(visible: str, errors: list[str]) -> None:
    prose = _prose_regions(visible)
    # Collapse wrapping so a wrapped sentence still counts as one.
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
        # Short form ok: Review may name a unique prefix of length >= 7.
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
    errors: list[str] = []
    _check_markers(text, errors)
    _check_headings(text, errors)
    _check_mermaid(text, errors)

    visible = _strip_comments(text)
    _check_placeholders(visible, errors)
    _check_how_to_test(text, errors)
    _check_ste(visible, errors)
    _check_review(text, errors)
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
