"""A post-merge block with the old docs line asks for a refresh, with no version bump."""

from __future__ import annotations

import json

from cairnkit import __version__, githook, refresh
from cairnkit.cli import main
from cairnkit.paths import find_project


def _stamp_path(repo):
    return repo.parent / f"{repo.name}.memory" / refresh.STAMP


def _stamp_current(repo) -> None:
    _stamp_path(repo).write_text(
        json.dumps({"version": __version__, "at": "2026-10-30T00:00:00+00:00", "blocks": []})
        + "\n",
        encoding="utf-8",
    )


# The first line of the docs check that older versions wrote into post-merge.
OLD_MARK = "# cairnkit:docs-check"


def test_repo_line_when_post_merge_still_holds_the_docs_check(repo):
    assert main(["init"]) == 0
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    project = find_project()
    assert refresh.repo_line(project, None) is None

    hook = repo / ".git" / "hooks" / "post-merge"
    body = f"{OLD_MARK}\necho old\n{githook.quiet_body('post-merge')}"
    hook.write_text(f"#!/bin/sh\n{githook.START}\n{body}{githook.END}\n")
    _stamp_current(repo)
    line = refresh.repo_line(project, None)
    assert line and "memory init --refresh" in line

    assert main(["init", "--refresh"]) == 0
    assert OLD_MARK not in hook.read_text()
    assert "hook post-merge" in hook.read_text()
    assert refresh.repo_line(project, None) is None


def test_the_post_merge_hook_has_no_docs_check(repo):
    assert main(["init"]) == 0
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    text = (repo / ".git" / "hooks" / "post-merge").read_text()
    assert "docs" not in text
