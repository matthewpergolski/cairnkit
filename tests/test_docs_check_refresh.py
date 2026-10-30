"""Post-merge docs-check marker nudges refresh without a package version bump."""

from __future__ import annotations

import json

from cairnkit import __version__, githook, refresh
from cairnkit.cli import main
from cairnkit.paths import find_project


def _stamp_path(repo):
    return repo.parent / f"{repo.name}.memory" / refresh.STAMP


def test_repo_line_when_post_merge_lacks_docs_check_marker(repo):
    """Same package version, old quiet-only post-merge: still ask for refresh."""
    assert main(["init"]) == 0
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    project = find_project()
    assert refresh.repo_line(project, None) is None

    hook = repo / ".git" / "hooks" / "post-merge"
    old = f"#!/bin/sh\n{githook.START}\n{githook.quiet_body('post-merge')}{githook.END}\n"
    hook.write_text(old)
    assert githook.DOCS_CHECK_MARK not in hook.read_text()

    stamp = _stamp_path(repo)
    stamp.write_text(
        json.dumps({"version": __version__, "at": "2026-10-30T00:00:00+00:00", "blocks": []})
        + "\n",
        encoding="utf-8",
    )
    assert __version__ == "0.2.0"
    line = refresh.repo_line(project, None)
    assert line and "memory init --refresh" in line

    assert main(["init", "--refresh"]) == 0
    text = hook.read_text()
    assert githook.DOCS_CHECK_MARK in text
    assert "docs --check" in text
    assert refresh.repo_line(project, None) is None
