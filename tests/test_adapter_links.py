"""A hook install writes no file through a link: not into a tracked file, not outside the repo.

`git ls-files -- .codex/hooks.json` prints nothing and exits 0 when `.codex` is a tracked link to
a tracked folder, so the check that a file is tracked cannot see the link.
"""

from __future__ import annotations

import json

import pytest
from conftest import git

from cairnkit import adapters
from cairnkit.cli import main
from cairnkit.paths import find_project

NAMES = ["claude", "codex", "cursor", "grok", "pi", "opencode"]


def top(name: str) -> str:
    return adapters.ADAPTERS[name].rel.split("/")[0]


def under_top(name: str) -> str:
    return adapters.ADAPTERS[name].rel.split("/", 1)[1]


def files_in(folder) -> dict[str, str]:
    return {
        p.relative_to(folder).as_posix(): p.read_text() for p in folder.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("name", NAMES)
def test_a_tracked_link_to_a_tracked_folder_is_not_written(repo, name):
    held = repo / "cfg" / under_top(name)
    held.parent.mkdir(parents=True)
    held.write_text("{}\n")
    (repo / top(name)).symlink_to("cfg")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "link")
    steps = adapters.apply(find_project(repo), name, True, False, [repo])
    assert held.read_text() == "{}\n"
    assert git(repo, "status", "--porcelain") == ""
    assert any(step.startswith("skip ") and "link" in step for step in steps), steps


@pytest.mark.parametrize("name", NAMES)
def test_a_link_out_of_the_repo_is_not_written(repo, tmp_path, name):
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / top(name)).symlink_to(outside)
    steps = adapters.apply(find_project(repo), name, True, False, [repo])
    assert files_in(outside) == {}
    assert any(step.startswith("skip ") for step in steps), steps


@pytest.mark.parametrize("name", NAMES)
def test_an_uninstall_removes_nothing_through_a_link(repo, tmp_path, name):
    outside = tmp_path / "outside"
    outside.mkdir()
    adapters.apply(find_project(repo), name, True, False, [repo])
    (repo / top(name)).rename(outside / "real")
    (repo / top(name)).symlink_to(outside / "real")
    before = files_in(outside)
    assert before
    adapters.apply(find_project(repo), name, False, False, [repo])
    assert files_in(outside) == before


def test_hooks_install_still_writes_a_plain_folder(repo, mem):
    assert main(["hooks", "install", "--agent", "codex"]) == 0
    hooks = json.loads((repo / ".codex" / "hooks.json").read_text())
    assert "SessionStart" in hooks["hooks"]


def test_the_rules_block_goes_through_no_folder_link_that_the_repo_brought(
    repo, mem, tmp_path, capsys
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / ".cursor").symlink_to(outside)
    (repo / "sub").symlink_to(outside)
    git(repo, "add", ".cursor", "sub")
    git(repo, "commit", "-qm", "links")
    assert main(["instructions", "--write-instructions"]) == 0
    assert files_in(outside) == {}
    assert "link that git tracks" in capsys.readouterr().out
    assert main(["instructions", "--write-instructions", "--instructions-file", "sub/x.md"]) == 1
    assert files_in(outside) == {}
