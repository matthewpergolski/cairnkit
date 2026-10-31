"""scripts/check_pr_body.py: PR descriptions stay human-shaped and unmarked."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_pr_body.py"

HEADINGS = [
    "TL;DR",
    "How it works",
    "Summary",
    "Files changed",
    "How to test",
    "Review",
]

SAMPLE_SHA = "abcdef1234567890abcdef1234567890abcdef12"


def load_mod():
    spec = importlib.util.spec_from_file_location("check_pr_body", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return load_mod()


def good_body(*, mention_products: bool = False, head_sha: str = SAMPLE_SHA) -> str:
    products = ""
    if mention_products:
        products = "\nHooks cover Claude, Cursor, and Codex as product names in adapters.\n"
    short = head_sha[:7]
    return f"""## TL;DR

After merge, CI rejects unmarked or AI-attributed PR bodies.
{products}
## How it works

```mermaid
flowchart LR
  A[PR body] --> B{{Shape and markers ok?}}
  B -->|no| C[Fail CI]
  B -->|yes| D[Pass]
```

Notice that the check reads the PR body text only.

## Summary

Adds a PR-body shape check and a template. Leaves the identity script's
commit rules alone.

## Files changed

| Purpose | Files |
| --- | --- |
| PR body check | `scripts/check_pr_body.py`, `tests/test_check_pr_body.py` |
| Template | `.github/pull_request_template.md` |

## How to test

- Unit: `uv run pytest tests/test_check_pr_body.py -q` — pass
- Smoke: not needed, because the unit cases cover the CLI exits
- End-to-end: not needed, because CI only invokes the script on the event body

## Review

- accepted: no open findings on this check
- Head: {short}
"""


def test_good_body_is_clean(mod):
    assert mod.check_body(good_body()) == []


def test_product_names_claude_cursor_codex_are_allowed(mod):
    assert mod.check_body(good_body(mention_products=True)) == []


def test_cursor_agent_pr_body_marker_is_reported(mod):
    body = good_body() + "\n<!-- CURSOR_AGENT_PR_BODY_BEGIN -->\n"
    errors = mod.check_body(body)
    assert errors
    assert any("CURSOR_AGENT_PR_BODY" in e for e in errors)
    joined = "\n".join(errors)
    assert "Fix:" in joined


def test_open_in_cursor_or_web_footer_is_reported(mod):
    for phrase in ("Open in Cursor", "Open in Web"):
        body = good_body() + f'\n<img alt="{phrase}" src="x.png">\n'
        errors = mod.check_body(body)
        assert any(phrase in e or "Open in" in e for e in errors), phrase
        assert "Fix:" in "\n".join(errors)


def test_generated_with_is_reported(mod):
    body = good_body().replace(
        "- accepted: no open findings on this check\n",
        "- accepted: no open findings on this check\n\nGenerated with Claude\n",
    )
    errors = mod.check_body(body)
    assert any("Generated with" in e for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_model_ids_are_reported_but_bare_product_names_are_not(mod):
    clean = good_body(mention_products=True)
    assert mod.check_body(clean) == []
    for model in (
        "claude-opus-4",
        "gpt-4o",
        "gemini-2.5-pro",
        "composer-1",
        "o3-mini",
    ):
        body = clean.replace(
            "Hooks cover Claude, Cursor, and Codex as product names in adapters.",
            f"Ran on {model} for this change.",
        )
        errors = mod.check_body(body)
        assert any(model in e for e in errors), model
        assert "Fix:" in "\n".join(errors)


def test_cursor_asset_filenames_are_not_model_ids(mod):
    body = good_body().replace(
        "- accepted: no open findings on this check\n",
        "- accepted: no open findings on this check\n\n![x](https://example.com/open-in-cursor-dark.png)\n",
    )
    # Asset names must not trip the model-id rule; the Open in * phrases still do.
    assert not any("model id" in e for e in mod.check_body(body))


def test_missing_heading_is_reported(mod):
    body = good_body().replace("## Review\n", "## Notes\n")
    errors = mod.check_body(body)
    assert any("Review" in e for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_headings_out_of_order_are_reported(mod):
    body = good_body()
    # Swap Summary and Files changed heading lines only.
    body = body.replace("## Summary\n", "## FILES_TMP\n", 1)
    body = body.replace("## Files changed\n", "## Summary\n", 1)
    body = body.replace("## FILES_TMP\n", "## Files changed\n", 1)
    errors = mod.check_body(body)
    assert any("order" in e.lower() or "heading" in e.lower() for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_duplicated_template_body_fails_and_names_repeated_heading(mod):
    """Two full six-section pastes must fail; a single copy must pass."""
    single = good_body()
    assert mod.check_body(single) == []
    duplicated = single + "\n" + single
    errors = mod.check_body(duplicated)
    assert errors
    # Every required heading appears twice; each must be named.
    for title in HEADINGS:
        assert any(f"heading {title!r}" in e and "appears" in e and "times" in e for e in errors), (
            title
        )
    assert all("Fix:" in e for e in errors)
    # First error names the first template heading (TL;DR).
    assert "heading 'TL;DR'" in errors[0] or 'heading "TL;DR"' in errors[0]


def test_missing_mermaid_fence_is_reported(mod):
    body = good_body().replace("```mermaid\n", "```\n", 1)
    errors = mod.check_body(body)
    assert any("mermaid" in e.lower() for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_mermaid_outside_how_it_works_is_reported(mod):
    """Mermaid must sit under How it works, not only elsewhere."""
    body = good_body()
    # good_body uses an f-string, so the mermaid node is a single-brace label.
    old_how = (
        "## How it works\n\n```mermaid\nflowchart LR\n  A[PR body] --> B{Shape and markers ok?}\n"
        "  B -->|no| C[Fail CI]\n  B -->|yes| D[Pass]\n```\n\n"
        "Notice that the check reads the PR body text only.\n"
    )
    assert old_how in body
    body = body.replace(
        old_how,
        "## How it works\n\nNotice that the check reads the PR body text only.\n",
        1,
    )
    body = body.replace(
        "## Summary\n\n",
        "## Summary\n\n```mermaid\nflowchart LR\n  X --> Y\n```\n\n",
        1,
    )
    errors = mod.check_body(body)
    assert any("mermaid" in e.lower() and "How it works" in e for e in errors)
    assert "Fix:" in "\n".join(errors)


@pytest.mark.parametrize(
    "needle",
    [
        "Pending",
        "TBD",
        "TODO",
        "paste the body",
        "once the PR number is known",
    ],
)
def test_placeholder_text_is_reported(mod, needle):
    body = good_body().replace(
        "After merge, CI rejects unmarked or AI-attributed PR bodies.",
        f"After merge, CI rejects unmarked bodies. {needle}.",
    )
    errors = mod.check_body(body)
    assert any("placeholder" in e.lower() or needle.lower() in e.lower() for e in errors), errors
    assert "Fix:" in "\n".join(errors)


def test_how_to_test_requires_exactly_three_labeled_lines(mod):
    body = good_body().replace(
        "## How to test\n\n"
        "- Unit: `uv run pytest tests/test_check_pr_body.py -q` — pass\n"
        "- Smoke: not needed, because the unit cases cover the CLI exits\n"
        "- End-to-end: not needed, because CI only invokes the script on the event body\n",
        "## How to test\n\n"
        "- Unit: `uv run pytest tests/test_check_pr_body.py -q` — pass\n"
        "- Smoke: not needed, because the unit cases cover the CLI exits\n",
        1,
    )
    errors = mod.check_body(body)
    assert any("How to test" in e for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_how_to_test_line_needs_command_result_or_not_needed(mod):
    body = good_body().replace(
        "- Smoke: not needed, because the unit cases cover the CLI exits\n",
        "- Smoke: maybe later\n",
        1,
    )
    errors = mod.check_body(body)
    assert any("Smoke" in e or "How to test" in e for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_ste_prose_sentence_over_25_words_is_reported(mod):
    long = (
        "This sentence has many extra words so that the rough STE word count "
        "check must fail when the prose goes past twenty five words in one go "
        "right here now."
    )
    assert len(long.split()) > 25
    body = good_body().replace(
        "Notice that the check reads the PR body text only.",
        long,
        1,
    )
    errors = mod.check_body(body)
    assert any("25" in e or "word" in e.lower() for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_ste_skips_code_tables_and_mermaid(mod):
    """Long lines inside fences or tables must not trip the STE check."""
    body = good_body().replace(
        "```mermaid\nflowchart LR\n  A[PR body] --> B{{Shape and markers ok?}}\n"
        "  B -->|no| C[Fail CI]\n  B -->|yes| D[Pass]\n```",
        "```mermaid\nflowchart LR\n  A[" + "word " * 30 + "] --> B\n```",
        1,
    )
    body = body.replace(
        "| PR body check | `scripts/check_pr_body.py`, `tests/test_check_pr_body.py` |",
        "| PR body check | `" + "word " * 30 + "` |",
        1,
    )
    assert mod.check_body(body) == []


def test_review_requires_disposition_findings(mod):
    body = good_body().replace(
        "## Review\n\n- accepted: no open findings on this check\n- Head: abcdef1\n",
        "## Review\n\n- Head: abcdef1\n- Independent review found nothing to change.\n",
        1,
    )
    errors = mod.check_body(body)
    joined = "\n".join(errors).lower()
    assert "fixed" in joined or "accepted" in joined or "rejected" in joined
    assert "Fix:" in "\n".join(errors)


def test_review_requires_head_sha(mod):
    body = good_body().replace(
        "## Review\n\n- accepted: no open findings on this check\n- Head: abcdef1\n",
        "## Review\n\n- accepted: no open findings on this check\n",
        1,
    )
    errors = mod.check_body(body)
    assert any("sha" in e.lower() or "head" in e.lower() for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_review_head_sha_must_match_env_when_set(mod, monkeypatch):
    monkeypatch.setenv("PR_HEAD_SHA", SAMPLE_SHA)
    ok = good_body(head_sha=SAMPLE_SHA)
    assert mod.check_body(ok) == []
    bad = good_body(head_sha="0000000111111111111111111111111111111111")
    errors = mod.check_body(bad)
    assert any("sha" in e.lower() or "head" in e.lower() for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_ai_coauthor_trailer_in_body_is_reported(mod):
    body = good_body() + "\nCo-authored-by: Neo <neo@example.com>\n"
    errors = mod.check_body(body)
    assert any("co-authored" in e.lower() or "trailer" in e.lower() for e in errors)
    assert "Fix:" in "\n".join(errors)


def test_cli_exits_1_on_bad_body(tmp_path):
    bad = tmp_path / "body.md"
    bad.write_text("no headings\n", encoding="utf-8")
    result = subprocess.run(
        ["python3", str(SCRIPT), str(bad)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "Fix:" in result.stderr


def test_cli_exits_0_on_good_body(tmp_path):
    path = tmp_path / "body.md"
    path.write_text(good_body(), encoding="utf-8")
    env = os.environ.copy()
    env["PR_HEAD_SHA"] = SAMPLE_SHA
    result = subprocess.run(
        ["python3", str(SCRIPT), str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert "pr-body: ok" in result.stdout


def test_required_headings_constant_matches_template_expectation(mod):
    assert list(mod.REQUIRED_HEADINGS) == HEADINGS


def test_pull_request_template_has_six_headings_and_mermaid(mod):
    """Skeleton may fail Review readiness; structure must still match."""
    template = ROOT / ".github" / "pull_request_template.md"
    assert template.is_file(), "add .github/pull_request_template.md with the six headings"
    text = template.read_text(encoding="utf-8")
    for title in HEADINGS:
        assert f"## {title}" in text
    assert "```mermaid" in text
    # Template Review is intentionally empty of findings/sha (review-gate owns Pending).
    errors = mod.check_body(text)
    assert any("Review" in e or "sha" in e.lower() or "accepted" in e.lower() for e in errors)


def test_pr_standards_workflow_exists_and_is_self_contained():
    path = ROOT / ".github" / "workflows" / "pr-standards.yml"
    assert path.is_file(), "add .github/workflows/pr-standards.yml for other repos to copy"
    text = path.read_text(encoding="utf-8")
    assert "pull_request" in text
    for event in ("opened", "edited", "synchronize", "reopened"):
        assert event in text
    assert "scripts/check_pr_body.py" in text
    assert "PR_HEAD_SHA" in text
    # Copyable pair must not require cairnkit-only jobs.
    assert "check_identity" not in text
    assert "check_review_gate" not in text
    assert "import cairnkit" not in text
    assert "from cairnkit" not in text


def test_check_pr_body_is_stdlib_only():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import cairnkit" not in source
    assert "from cairnkit" not in source
    # No third-party imports: only stdlib modules after future annotations.
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("from ") or stripped.startswith("import "):
            assert not stripped.startswith("from cairnkit")
            assert not stripped.startswith("import cairnkit")
            mod = stripped.split()[1].split(".")[0].split(",")[0]
            if mod == "__future__":
                continue

            assert mod in {
                "argparse",
                "os",
                "re",
                "sys",
                "pathlib",
                "typing",
                "textwrap",
                "string",
                "collections",
                "dataclasses",
                "functools",
                "itertools",
                "json",
                "html",
                "subprocess",
                "shutil",
            }, stripped


def test_cursor_com_footer_link_is_reported_even_without_open_phrase(mod):
    """Root cause: PR-body tool footer uses cursor.com links/images."""
    body = good_body() + (
        "\n"
        '<div><a href="https://cursor.com/agents/bc-x">'
        '<img alt="agent" src="https://cursor.com/assets/images/open-in-web-dark.png">'
        "</a></div>\n"
    )
    errors = mod.check_body(body)
    joined = "\n".join(errors).lower()
    assert "cursor.com" in joined or "footer" in joined
    assert "Fix:" in "\n".join(errors)


def test_exactly_six_required_headings_wrong_count_fails(mod):
    """Root cause: wrong body section count."""
    dropped = good_body().replace("## Files changed\n", "## Changed files\n", 1)
    errors = mod.check_body(dropped)
    assert any("Files changed" in e or "heading" in e.lower() for e in errors)


def test_pr_workflow_doc_exists_and_orders_review_before_ci_wait():
    """Root cause: review waiting on CI / review not before ready."""
    path = ROOT / "docs" / "pr-workflow.md"
    assert path.is_file(), "add docs/pr-workflow.md with the short STE flow"
    text = path.read_text(encoding="utf-8").casefold()
    assert "review" in text
    assert "ci" in text
    assert "pr_body" in text or "check_pr_body" in text
    assert "before" in text and ("wait" in text or "matrix" in text or "ready" in text)
