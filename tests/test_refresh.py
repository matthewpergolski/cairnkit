"""The tool version that last wrote a repo's files, and `memory init --refresh`."""

from __future__ import annotations

import json

import pytest

from cairnkit import __version__, adapters, githook, instructions, refresh
from cairnkit.cli import main
from cairnkit.paths import find_project

OLD_BLOCK = f"{instructions.START}\n## Project memory\n\nOld text.\n{instructions.END}\n"


def stamp(repo):
    return json.loads((repo.parent / "proj.memory" / refresh.STAMP).read_text())


def test_refresh_migrates_tracked_blocks_and_leaves_hand_written_text(repo, capsys):
    assert main(["init"]) == 0
    agents = repo / "AGENTS.md"
    agents.write_text(f"# Team rules\n\nUse uv.\n\n{OLD_BLOCK}\nMore team text.\n")
    claude = repo / "CLAUDE.md"
    claude.write_text("@AGENTS.md\n")
    local = repo / "CLAUDE.local.md"
    local.write_text(f"# Mine\n\n{OLD_BLOCK}")
    assert main(["init", "--refresh"]) == 0
    first = agents.read_text()
    assert instructions.START not in first
    assert "Old text." not in first
    assert first.startswith("# Team rules\n\nUse uv.\n\n")
    assert first.endswith("\nMore team text.\n")
    assert local.read_text().startswith("# Mine\n\n")
    assert instructions.block() in local.read_text()
    for _ in range(2):
        assert main(["init", "--refresh"]) == 0
        assert agents.read_text() == first
    assert claude.read_text() == "@AGENTS.md\n"  # no markers: never appended
    out = capsys.readouterr().out
    assert "remove the rules block" in out and "update the rules block" in out


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
    assert "would remove the rules block" in capsys.readouterr().out
    assert not (repo.parent / "proj.memory" / refresh.STAMP).exists()


def test_refresh_needs_a_memory(repo, capsys):
    assert main(["init", "--refresh"]) == 1
    assert "memory init" in capsys.readouterr().err


def test_writing_the_block_or_hooks_records_the_tool_version(repo):
    from cairnkit import harness_local

    assert main(["init"]) == 0
    assert main(["instructions", "--write-instructions", "local"]) == 0
    record = stamp(repo)
    assert record["version"] == __version__
    expected = sorted(["CLAUDE.local.md", *harness_local.rels()])
    assert record["blocks"] == expected
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    assert stamp(repo)["blocks"] == expected


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
        assert main(["instructions", "--write-instructions"]) == 1
        assert agents.read_text() == text
    assert "by hand" in capsys.readouterr().out
    agents.write_text("# Team\n")  # clear the broken block so a custom file can write
    assert main(["instructions", "--write-instructions", "--instructions-file", "X.md"]) == 0
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


OLD_BUILD = "6b4bdf0" + "1" * 33
NEW_BUILD = "81f8499" + "2" * 33


def _stale_post_merge(repo):
    """A post-merge block that an older build of the same version wrote."""
    hook = repo / ".git" / "hooks" / "post-merge"
    body = f"# cairnkit:docs-check\necho old\n{githook.quiet_body('post-merge')}"
    hook.write_text(f"#!/bin/sh\n{githook.START}\n{body}{githook.END}\n")


def test_a_notice_for_one_version_names_the_build_that_wrote_the_files(repo, monkeypatch):
    monkeypatch.setattr(refresh, "build_commit", lambda: OLD_BUILD)
    assert main(["init"]) == 0
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    assert stamp(repo)["commit"] == OLD_BUILD
    _stale_post_merge(repo)
    monkeypatch.setattr(refresh, "build_commit", lambda: NEW_BUILD)
    line = refresh.repo_line(find_project(), None)
    assert f"come from memory {__version__} @6b4bdf0; this is {__version__} @81f8499" in line
    assert "memory init --refresh" in line


def test_a_record_with_no_build_names_an_older_build(repo, monkeypatch):
    monkeypatch.setattr(refresh, "build_commit", lambda: NEW_BUILD)
    assert main(["init"]) == 0
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    path = repo.parent / "proj.memory" / refresh.STAMP
    path.write_text(json.dumps({"version": __version__, "at": "2026-10-30T00:00:00+00:00"}))
    _stale_post_merge(repo)
    line = refresh.repo_line(find_project(), None)
    assert (
        f"come from an older build of memory {__version__}; this is {__version__} @81f8499" in line
    )


def test_a_new_build_of_the_same_version_records_its_commit(repo, monkeypatch):
    monkeypatch.setattr(refresh, "build_commit", lambda: OLD_BUILD)
    assert main(["init"]) == 0
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    monkeypatch.setattr(refresh, "build_commit", lambda: NEW_BUILD)
    assert main(["init", "--refresh"]) == 0
    assert stamp(repo)["commit"] == NEW_BUILD
    assert refresh.repo_line(find_project(), None) is None


def load_text(capsys) -> str:
    capsys.readouterr()
    assert main(["load"]) == 0
    return capsys.readouterr().out


def repo_files(repo) -> dict[str, bytes]:
    git = repo / ".git"
    paths = [p for p in repo.rglob("*") if git not in p.parents] + [git / "config"]
    paths += [*(git / "hooks").rglob("*"), *(git / "info").rglob("*")]
    return {str(p): p.read_bytes() for p in paths if p.is_file()}


def files_from_another_build(monkeypatch) -> None:
    monkeypatch.setattr(refresh, "build_commit", lambda: OLD_BUILD)
    assert main(["init"]) == 0
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    assert main(["instructions", "--write-instructions"]) == 0
    monkeypatch.setattr(refresh, "build_commit", lambda: NEW_BUILD)


def test_another_build_that_writes_the_same_files_says_nothing(repo, monkeypatch, capsys):
    files_from_another_build(monkeypatch)
    assert "memory init --refresh" not in load_text(capsys)
    capsys.readouterr()
    assert main(["status"]) == 0
    assert "memory init --refresh" not in capsys.readouterr().out


def counted_plans(monkeypatch) -> list[bool]:
    calls = []
    plan = refresh._plan

    def counted(*args, **kwargs):
        calls.append(True)
        return plan(*args, **kwargs)

    monkeypatch.setattr(refresh, "_plan", counted)
    return calls


def new_process(monkeypatch) -> None:
    monkeypatch.setattr(refresh, "_compared", {})


def test_a_second_session_start_does_not_compare_the_same_builds_again(repo, monkeypatch, capsys):
    files_from_another_build(monkeypatch)
    plans = counted_plans(monkeypatch)
    assert "memory init --refresh" not in load_text(capsys)
    new_process(monkeypatch)
    assert "memory init --refresh" not in load_text(capsys)
    assert len(plans) == 1
    monkeypatch.setattr(refresh, "build_commit", lambda: "0c0ffee" + "3" * 33)
    new_process(monkeypatch)
    assert "memory init --refresh" not in load_text(capsys)
    assert len(plans) == 2


def test_a_cache_that_cannot_be_written_compares_once_in_one_load(
    repo, tmp_path, monkeypatch, capsys
):
    from cairnkit import hookrun

    files_from_another_build(monkeypatch)
    blocked = tmp_path / "not-a-folder"
    blocked.write_text("")
    monkeypatch.setenv("XDG_CACHE_HOME", str(blocked))
    plans = counted_plans(monkeypatch)
    passes = []
    run_load = hookrun.run_load
    monkeypatch.setattr(hookrun, "run_load", lambda *a, **k: passes.append(1) or run_load(*a, **k))
    assert hookrun.fitted_load(find_project(), None, 600, room=1)
    assert len(passes) > 1
    assert len(plans) == 1
    new_process(monkeypatch)
    new_rules_text(monkeypatch)
    assert "memory init --refresh" in load_text(capsys)
    assert len(plans) == 2


def new_rules_text(monkeypatch):
    text = instructions.text()
    monkeypatch.setattr(instructions, "text", lambda: text + "A rule of the new build.\n")


def new_hook_text(monkeypatch):
    body = githook.post_merge_body()
    monkeypatch.setattr(githook, "post_merge_body", lambda: body + "# the new build\n")


@pytest.mark.parametrize("change", [new_rules_text, new_hook_text])
def test_another_build_that_writes_other_files_asks_for_a_refresh(
    repo, monkeypatch, capsys, change
):
    files_from_another_build(monkeypatch)
    change(monkeypatch)
    origin = f"come from memory {__version__} @6b4bdf0; this is {__version__} @81f8499"
    before = repo_files(repo)
    assert origin in load_text(capsys)
    assert repo_files(repo) == before
    capsys.readouterr()
    assert main(["status"]) == 0
    assert origin in capsys.readouterr().out
    assert main(["init", "--refresh"]) == 0
    assert "memory init --refresh" not in load_text(capsys)


def test_a_build_with_no_commit_keeps_the_version_compare(repo, monkeypatch, capsys):
    files_from_another_build(monkeypatch)
    new_rules_text(monkeypatch)
    monkeypatch.setattr(refresh, "build_commit", lambda: None)
    assert "memory init --refresh" not in load_text(capsys)
