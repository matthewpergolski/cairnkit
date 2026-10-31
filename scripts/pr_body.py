#!/usr/bin/env python3
"""Render, validate, and set a six-section PR body (Option A).

Canonical body: text between one CURSOR_AGENT_PR_BODY_BEGIN/END pair when
present. A single cursor.com agent footer after END is packaging, not a
second copy. strip_agent_footer() returns the canonical six-section text.

Commands:
  python3 scripts/pr_body.py render PATH
  python3 scripts/pr_body.py check PATH
  python3 scripts/pr_body.py set --pr N --file PATH [--repo OWNER/NAME]

set validates the canonical body, then full-replaces via:
  gh pr edit N --body-file PATH

Cloud agents often get HTTP 403 from gh on PR edits. In that case set
prints the clean body and exits 3. The operator (or ManagePullRequest)
must paste that single clean body once. ManagePullRequest re-wraps with
markers + footer; the checker treats that as one copy, not two.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = ROOT / "scripts" / "check_pr_body.py"


def _load_check_mod():
    spec = importlib.util.spec_from_file_location("check_pr_body", CHECK_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {CHECK_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def strip_agent_footer(text: str) -> str:
    """Return the canonical six-section body (markers/footer removed)."""
    mod = _load_check_mod()
    canonical, _packaging = mod.canonical_pr_body(text)
    # Drop leftover packaging comments if present inside the extract.
    out = mod._HTML_COMMENT.sub("", canonical) if hasattr(mod, "_HTML_COMMENT") else canonical
    return out.strip() + "\n"


def validate_body(text: str) -> list[str]:
    mod = _load_check_mod()
    return mod.check_body(text)


def run_gh(argv: list[str]) -> tuple[int, str]:
    result = subprocess.run(argv, check=False, capture_output=True, text=True)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return int(result.returncode), result.stderr or ""


def set_body(*, pr: int, path: Path, repo: str | None = None) -> int:
    raw = path.read_text(encoding="utf-8")
    cleaned = strip_agent_footer(raw)
    problems = validate_body(cleaned)
    if problems:
        print(f"pr-body: {len(problems)} problem(s); refusing to set", file=sys.stderr)
        for line in problems:
            print(f"error: {line}", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as tmp:
        tmp.write(cleaned)
        tmp_path = tmp.name

    argv = ["gh", "pr", "edit", str(pr), "--body-file", tmp_path]
    if repo:
        argv.extend(["--repo", repo])
    try:
        result = run_gh(argv)
        if isinstance(result, tuple):
            code, stderr = result
        else:
            code, stderr = int(result), ""
        if code == 0:
            print(f"pr-body: set on #{pr} via gh pr edit --body-file")
            return 0
        err_l = stderr.casefold()
        is_403 = (
            "403" in err_l
            or "resource not accessible by integration" in err_l
            or "updatepullrequest" in err_l
        )
        if not is_403:
            print(f"pr-body: gh pr edit failed with exit {code}", file=sys.stderr)
            return code if code else 1
        # Common on cloud agents: integration token cannot updatePullRequest.
        print(
            "pr-body: gh pr edit failed (HTTP 403 on cloud agents). "
            "Paste the clean six-section body once via ManagePullRequest "
            "(it will wrap markers + footer; that is one copy under Option A). "
            "Do not paste a second copy outside the markers.",
            file=sys.stderr,
        )
        print("--- clean body begins ---")
        sys.stdout.write(cleaned)
        if not cleaned.endswith("\n"):
            print()
        print("--- clean body ends ---")
        return 3
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_render = sub.add_parser("render", help="print the canonical stripped body")
    p_render.add_argument("path")

    p_check = sub.add_parser("check", help="validate (Option A canonical rules)")
    p_check.add_argument("path")

    p_set = sub.add_parser("set", help="validate and gh pr edit --body-file")
    p_set.add_argument("--pr", type=int, required=True)
    p_set.add_argument("--file", required=True)
    p_set.add_argument("--repo", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "render":
        text = Path(args.path).read_text(encoding="utf-8")
        sys.stdout.write(strip_agent_footer(text))
        return 0

    if args.cmd == "check":
        text = Path(args.path).read_text(encoding="utf-8")
        problems = validate_body(text)
        if not problems:
            print("pr-body: ok")
            return 0
        print(f"pr-body: {len(problems)} problem(s)", file=sys.stderr)
        for line in problems:
            print(f"error: {line}", file=sys.stderr)
        return 1

    if args.cmd == "set":
        return set_body(pr=args.pr, path=Path(args.file), repo=args.repo)

    return 2


if __name__ == "__main__":
    sys.exit(main())
