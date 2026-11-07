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


def _codex_behind_a_link(repo, tmp_path):
    """Codex hooks from before -P, in a .codex folder that is the owner's link."""
    outside = tmp_path / "outside"
    outside.mkdir()
    adapters.apply(find_project(repo), "codex", True, False, [repo])
    hooks = repo / ".codex" / "hooks.json"
    hooks.write_text(hooks.read_text().replace(" -P -m cairnkit", " -m cairnkit"))
    (repo / ".codex").rename(outside / "codex")
    (repo / ".codex").symlink_to(outside / "codex")
    return outside / "codex" / "hooks.json"


def test_a_hook_file_behind_a_link_asks_for_no_refresh_that_cannot_write_it(
    repo, mem, tmp_path, capsys
):
    """The check skips the files that the writer skips. Else it asks for a refresh for ever."""
    from cairnkit import refresh

    held = _codex_behind_a_link(repo, tmp_path)
    before = held.read_text()
    project = find_project(repo)
    refresh.record(project, None)
    assert refresh.repo_line(project, None) is None
    capsys.readouterr()
    assert main(["init", "--refresh"]) == 0
    out = capsys.readouterr().out
    assert "skip" in out and ".codex" in out and "link" in out
    assert held.read_text() == before
    assert refresh.repo_line(project, None) is None


def test_init_names_only_the_agents_it_connected(repo, tmp_path, capsys, monkeypatch):
    from cairnkit import hooks_cmd

    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    monkeypatch.setattr(adapters, "detect", lambda project: ["claude", "codex"])
    (tmp_path / "outside").mkdir()
    (repo / ".codex").symlink_to(tmp_path / "outside")
    capsys.readouterr()
    assert main(["init", "--no-default-rules"]) == 0
    out = capsys.readouterr().out
    assert "Agents connected: claude." in out
    assert f"skip {repo / '.codex' / 'hooks.json'}: it is a link" in out


def test_a_linked_memory_folder_child_names_the_fix(repo, mem, tmp_path, capsys):
    """A facts folder on another disk is a link. A write there is refused, with the way out."""
    other = tmp_path / "other-disk"
    other.mkdir()
    (mem / "facts").rename(other / "facts")
    (mem / "facts").symlink_to(other / "facts")
    capsys.readouterr()
    assert main(["add", "A fact.", "--basis", "seen", "--source", "session:2026-11-01"]) != 0
    captured = capsys.readouterr()
    said = captured.out + captured.err
    assert "Not changed." in said
    assert "MEMORY_DIR" in said and "replace the link" in said
