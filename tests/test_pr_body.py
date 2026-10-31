"""scripts/pr_body.py: render, validate, and full-replace PR bodies without footers."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "pr_body.py"

SAMPLE_SHA = "abcdef1234567890abcdef1234567890abcdef12"

FOOTER = (
    "<!-- CURSOR_AGENT_PR_BODY_BEGIN -->\n"
    "<!-- CURSOR_AGENT_PR_BODY_END -->\n"
    '<div><a href="https://cursor.com/agents/bc-x">'
    '<img alt="Open in Web" src="https://cursor.com/assets/images/open-in-web-dark.png">'
    "</a>"
    '<a href="https://cursor.com/background-agent?bcId=bc-x">'
    '<img alt="Open in Cursor" src="https://cursor.com/assets/images/open-in-cursor-dark.png">'
    "</a></div>\n"
)


def load_mod():
    assert SCRIPT.is_file(), "add scripts/pr_body.py"
    spec = importlib.util.spec_from_file_location("pr_body", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return load_mod()


def clean_six_section(*, head_sha: str = SAMPLE_SHA) -> str:
    short = head_sha[:7]
    return f"""## TL;DR

Ship a clean PR body setter that strips agent footers.

## How it works

```mermaid
flowchart LR
  file[Body file] --> strip[Strip markers]
  strip --> check[check_pr_body]
  check --> set[gh pr edit body-file]
```

Notice that set always does a full replace from the file.

## Summary

Adds `scripts/pr_body.py` to render, validate, and set the body. Leaves identity rules alone.

## Files changed

| Purpose | Files |
| --- | --- |
| Body tool | `scripts/pr_body.py`, `tests/test_pr_body.py` |

## How to test

- Unit: `uv run pytest tests/test_pr_body.py -q` — pass
- Smoke: not needed, because unit cases cover strip and validate
- End-to-end: not needed, because set is mocked in unit tests

## Review

- accepted: no open findings on this tool
- Head: {short}
"""


def test_script_exists():
    assert SCRIPT.is_file(), "add scripts/pr_body.py (render, validate, set)"


def test_strip_removes_cursor_agent_markers_and_cursor_com_footer(mod):
    dirty = clean_six_section() + "\n" + FOOTER
    cleaned = mod.strip_agent_footer(dirty)
    assert "CURSOR_AGENT_PR_BODY" not in cleaned
    assert "cursor.com" not in cleaned.casefold()
    assert "Open in Cursor" not in cleaned
    assert "Open in Web" not in cleaned
    assert "## TL;DR" in cleaned
    assert "## Review" in cleaned


def test_strip_is_idempotent(mod):
    dirty = clean_six_section() + "\n" + FOOTER
    once = mod.strip_agent_footer(dirty)
    twice = mod.strip_agent_footer(once)
    assert once == twice


def test_validate_uses_check_pr_body(mod, monkeypatch):
    monkeypatch.setenv("PR_HEAD_SHA", SAMPLE_SHA)
    assert mod.validate_body(clean_six_section()) == []
    dirty = clean_six_section() + "\nPending\n"
    errors = mod.validate_body(dirty)
    assert errors
    assert any("placeholder" in e.lower() or "Pending" in e for e in errors)


def test_set_writes_stripped_body_via_gh_body_file(mod, tmp_path, monkeypatch):
    """Root cause: ManagePullRequest duplicates body+footer; set uses gh full replace."""
    path = tmp_path / "body.md"
    path.write_text(clean_six_section() + "\n" + FOOTER, encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run_gh(argv: list[str]) -> int:
        calls.append(list(argv))
        return 0

    monkeypatch.setenv("PR_HEAD_SHA", SAMPLE_SHA)
    monkeypatch.setattr(mod, "run_gh", fake_run_gh)

    rc = mod.set_body(pr=20, path=path, repo="matthewpergolski/cairnkit")
    assert rc == 0
    assert calls, "expected a gh pr edit --body-file invocation"
    flat = " ".join(" ".join(c) for c in calls)
    assert "gh" in flat
    assert "pr" in flat and "edit" in flat
    assert "--body-file" in flat
    body_file = None
    for c in calls:
        if "--body-file" in c:
            body_file = c[c.index("--body-file") + 1]
            break
    assert body_file is not None
    written = Path(body_file).read_text(encoding="utf-8")
    assert "CURSOR_AGENT_PR_BODY" not in written
    assert "cursor.com" not in written.casefold()


def test_cli_render_prints_stripped_body(tmp_path):
    path = tmp_path / "body.md"
    path.write_text(clean_six_section() + "\n" + FOOTER, encoding="utf-8")
    result = subprocess.run(
        ["python3", str(SCRIPT), "render", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CURSOR_AGENT_PR_BODY" not in result.stdout
    assert "cursor.com" not in result.stdout.casefold()
    assert "## TL;DR" in result.stdout


def test_cli_check_fails_on_placeholder(tmp_path):
    path = tmp_path / "body.md"
    path.write_text(
        clean_six_section().replace("Ship a clean", "Ship a Pending"),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PR_HEAD_SHA"] = SAMPLE_SHA
    result = subprocess.run(
        ["python3", str(SCRIPT), "check", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert "Fix:" in result.stderr or "problem" in result.stderr.casefold()


def test_pr_body_is_stdlib_only():
    assert SCRIPT.is_file()
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import cairnkit" not in source
    assert "from cairnkit" not in source
