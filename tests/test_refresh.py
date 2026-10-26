"""The tool version that last wrote a repo's files, and `memory init --refresh`."""

from __future__ import annotations

import json

from cairnkit import __version__, adapters, githook, instructions, refresh
from cairnkit.cli import main
from cairnkit.paths import find_project

OLD_BLOCK = f"{instructions.START}\n## Project memory\n\nOld text.\n{instructions.END}\n"


def stamp(repo):
    return json.loads((repo.parent / "proj.memory" / refresh.STAMP).read_text())


def test_refresh_replaces_the_rules_block_once_and_the_file_does_not_grow(repo, capsys):
    assert main(["init"]) == 0
    agents = repo / "AGENTS.md"
    agents.write_text(f"# Team rules\n\nUse uv.\n\n{OLD_BLOCK}\nMore team text.\n")
    claude = repo / "CLAUDE.md"
    claude.write_text("@AGENTS.md\n")
    assert main(["init", "--refresh"]) == 0
    first = agents.read_text()
    assert first.count(instructions.START) == 1
    assert first.count(instructions.END) == 1
    assert instructions.block() in first
    assert "Old text." not in first
    assert first.startswith("# Team rules\n\nUse uv.\n\n")
    assert first.endswith("\nMore team text.\n")
    for _ in range(2):
        assert main(["init", "--refresh"]) == 0
        assert agents.read_text() == first
    assert claude.read_text() == "@AGENTS.md\n"  # no markers: never appended
    assert "update the rules block" in capsys.readouterr().out


def test_refresh_leaves_a_broken_block_alone_and_says_so(repo, capsys):
    assert main(["init"]) == 0
    agents = repo / "AGENTS.md"
    text = f"{instructions.START}\nOld text, the end marker is lost.\n"
    agents.write_text(text)
    assert main(["init", "--refresh"]) == 1
    assert agents.read_text() == text
    out = capsys.readouterr().out
    assert "AGENTS.md" in out and "by hand" in out


def test_refresh_rewrites_hooks_that_exist_and_adds_no_new_ones(repo, capsys):
    assert main(["init"]) == 0
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    old = "/old/python -m cairnkit hook session-start --agent claude"
    settings.write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": old}]}]}})
    )
    pre_commit = repo / ".git" / "hooks" / "pre-commit"
    pre_commit.write_text(f"#!/bin/sh\n{githook.START}\nold body\n{githook.END}\necho mine\n")
    assert main(["init", "--refresh"]) == 0
    commands = json.dumps(json.loads(settings.read_text()))
    assert old not in commands
    assert adapters.hook_command("session-start", "claude") in commands
    hook = pre_commit.read_text()
    assert hook.count(githook.START) == 1
    assert "old body" not in hook and hook.endswith("echo mine\n")
    assert not (repo / ".codex").exists()
    assert not (repo / ".git" / "hooks" / "post-checkout").exists()


def test_refresh_dry_run_changes_nothing(repo, capsys):
    assert main(["init"]) == 0
    agents = repo / "AGENTS.md"
    agents.write_text(OLD_BLOCK)
    assert main(["init", "--refresh", "--dry-run"]) == 0
    assert agents.read_text() == OLD_BLOCK
    assert "would update the rules block" in capsys.readouterr().out
    assert not (repo.parent / "proj.memory" / refresh.STAMP).exists()


def test_refresh_needs_a_memory(repo, capsys):
    assert main(["init", "--refresh"]) == 1
    assert "memory init" in capsys.readouterr().err


def test_writing_the_block_or_hooks_records_the_tool_version(repo):
    assert main(["init"]) == 0
    assert main(["instructions", "--write-instructions", "local"]) == 0
    record = stamp(repo)
    assert record["version"] == __version__
    assert record["blocks"] == ["CLAUDE.local.md"]
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    assert stamp(repo)["blocks"] == ["CLAUDE.local.md"]


def test_repo_line_shows_when_the_files_are_older_than_the_tool(repo, monkeypatch):
    assert main(["init"]) == 0
    project = find_project()
    assert refresh.repo_line(project, None) is None  # nothing written yet
    (repo / "AGENTS.md").write_text(OLD_BLOCK)  # written before versions were recorded
    line = refresh.repo_line(project, None)
    assert line and "memory init --refresh" in line
    assert main(["init", "--refresh"]) == 0
    assert refresh.repo_line(project, None) is None
    monkeypatch.setattr(refresh, "tool_version", lambda: "9.0.0")
    line = refresh.repo_line(project, None)
    assert f"memory {__version__}" in line and "9.0.0" in line


def test_refresh_refuses_a_git_hook_with_a_lost_end_marker(repo, capsys):
    assert main(["init"]) == 0
    pre_commit = repo / ".git" / "hooks" / "pre-commit"
    text = f"#!/bin/sh\n{githook.START}\nold body, the end marker is lost\necho mine\n"
    pre_commit.write_text(text)
    for _ in range(2):
        assert main(["init", "--refresh"]) == 1
        assert pre_commit.read_text() == text
    out = capsys.readouterr().out
    assert "pre-commit" in out and "by hand" in out


def test_refresh_refuses_a_git_hook_with_two_blocks(repo, capsys):
    assert main(["init"]) == 0
    hook = repo / ".git" / "hooks" / "post-checkout"
    block = f"{githook.START}\nold\n{githook.END}\n"
    hook.write_text("#!/bin/sh\n" + block + block)
    assert main(["init", "--refresh"]) == 1
    assert hook.read_text() == "#!/bin/sh\n" + block + block


def test_hooks_install_refuses_a_git_hook_with_a_lost_marker(repo, capsys):
    pre_commit = repo / ".git" / "hooks" / "pre-commit"
    text = f"#!/bin/sh\necho mine\n{githook.END}\n"  # the start marker is lost
    pre_commit.write_text(text)
    assert main(["hooks", "install", "--agent", "generic"]) == 1
    assert pre_commit.read_text() == text
    out = capsys.readouterr().out
    assert "by hand" in out


def test_write_instructions_refuses_a_lost_end_marker(repo, capsys):
    agents = repo / "AGENTS.md"
    text = f"# Team\n\n{instructions.START}\nOld text, the end marker is lost.\n"
    agents.write_text(text)
    for _ in range(2):
        assert main(["instructions", "--write-instructions", "shared"]) == 1
        assert agents.read_text() == text
    assert "by hand" in capsys.readouterr().out
    assert (
        main(["instructions", "--write-instructions", "shared", "--instructions-file", "X.md"]) == 0
    )
    assert (repo / "X.md").read_text().count(instructions.START) == 1


def test_refresh_leaves_checkouts_without_memory_hooks_alone(repo, capsys):
    from conftest import add_worktree

    assert main(["init"]) == 0
    other = add_worktree(repo, "feature")
    assert main(["init"]) == 0  # link the new worktree
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    old = "/old/python -m cairnkit hook session-start --agent claude"
    settings.write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": old}]}]}})
    )
    assert main(["init", "--refresh"]) == 0
    assert adapters.hook_command("session-start", "claude") in settings.read_text()
    assert not (other / ".claude").exists()


def test_a_second_write_of_the_same_version_leaves_the_record_alone(repo, monkeypatch):
    assert main(["init"]) == 0
    monkeypatch.setenv("MEMORY_NOW", "2026-10-25T09:00:00+00:00")
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    path = repo.parent / "proj.memory" / refresh.STAMP
    first = path.read_text()
    monkeypatch.setenv("MEMORY_NOW", "2026-10-25T10:00:00+00:00")
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    assert main(["init", "--refresh"]) == 0
    assert path.read_text() == first


def test_refresh_refuses_a_shared_hook_whose_start_marker_is_lost(repo, capsys):
    assert main(["init"]) == 0
    hook = repo / githook.SHARED_DIR / "commit-msg"
    hook.parent.mkdir()
    text = f"#!/bin/sh\nold guard\n{githook.END}\n"
    hook.write_text(text)
    assert main(["init", "--refresh"]) == 1
    assert hook.read_text() == text
    assert "by hand" in capsys.readouterr().out
    assert not (repo.parent / "proj.memory" / refresh.STAMP).exists()  # no new version recorded


def test_refresh_refuses_a_broken_shared_pre_commit_hook(repo, capsys):
    assert main(["init"]) == 0
    folder = repo / githook.SHARED_DIR
    folder.mkdir()
    (folder / "commit-msg").write_text(f"#!/bin/sh\n{githook.START}\nok\n{githook.END}\n")
    broken = f"#!/bin/sh\n{githook.START}\nold, end lost\n"
    (folder / "pre-commit").write_text(broken)
    assert main(["init", "--refresh"]) == 1
    assert (folder / "pre-commit").read_text() == broken


def test_refresh_rewrites_only_the_shared_hooks_that_hold_a_block(repo, capsys):
    assert main(["init"]) == 0
    folder = repo / githook.SHARED_DIR
    folder.mkdir()
    commit_msg = folder / "commit-msg"
    commit_msg.write_text(f"#!/bin/sh\n{githook.START}\nold guard\n{githook.END}\necho team\n")
    team = "#!/bin/sh\necho the team's own pre-commit\n"
    (folder / "pre-commit").write_text(team)
    assert main(["init", "--refresh"]) == 0
    first = commit_msg.read_text()
    assert "old guard" not in first and githook.GUARD_MARK in first
    assert first.count(githook.START) == 1 and first.endswith("echo team\n")
    assert (folder / "pre-commit").read_text() == team
    assert not (folder / "post-checkout").exists()
    for _ in range(2):  # repeated refresh: single blocks, byte-identical files
        assert main(["init", "--refresh"]) == 0
        assert commit_msg.read_text() == first
        assert (folder / "pre-commit").read_text() == team
