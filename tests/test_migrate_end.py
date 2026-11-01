"""A migration of a real prose folder has one end, and it leaves one active copy of each file."""

from pathlib import Path

import pytest
from conftest import git
from test_migrate import sibling, snapshot

from cairnkit import skills
from cairnkit.cli import main

OLD_CHECKER = """\
import subprocess

def check_secrets():
    env = open(".env").read()

def check_worktree_queue():
    pass

def check_status_commit():
    subprocess.run(["git", "rev-list", "--count", "HEAD"])

def check_pointers():
    pass

def check_note_limits():
    max_lines = 200

def check_changelog_entry():
    pass
"""
CLAUDE = (
    "# Project\n\n"
    "Read `memory-bank/status.md` first.\n"
    "Then run `uv run tools/check_memory.py`.\n"
    "Update `memory-bank/log.md` at the end.\n"
    "See docs/working/memory-bank.md for how it works.\n"
)
SETTINGS = (
    '{"hooks":{"SessionStart":[{"matcher":"","hooks":['
    '{"type":"command","command":"uv run tools/check_memory.py"}]}]}}\n'
)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def old_layout(repo: Path) -> Path:
    """Instructions that teach the old layout, a checker, a hook, and a real old folder."""
    write(repo / "tools" / "check_memory.py", OLD_CHECKER)
    write(repo / "CLAUDE.md", CLAUDE)
    write(repo / "docs" / "working" / "memory-bank.md", "# Bank\nKeep memory-bank/status.md.\n")
    write(repo / ".claude" / "settings.json", SETTINGS)
    write(repo / ".gitignore", ".worktrees/\nmemory-bank/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "old layout")
    bank = repo / "memory-bank"
    write(bank / "status.md", "# Status\nPR 96 is open. Do not merge.\n")
    write(bank / "log.md", "# Log\n- 2026-10-09 The venv was rebuilt.\n")
    write(bank / "decisions.md", "# Decisions\n- 2026-10-09 The stack is Django.\n")
    return repo


def fix_every_item(repo: Path) -> None:
    """What an agent does with the task."""
    write(repo / "CLAUDE.md", "# Project\n\nRun `memory load`.\n")
    (repo / "docs" / "working" / "memory-bank.md").unlink()
    write(repo / ".claude" / "settings.json", '{"hooks":{}}\n')


def migrate(capsys, *args: str) -> str:
    capsys.readouterr()
    assert main(["migrate", "--preset", "none", *args]) == 0
    return capsys.readouterr().out


def load(capsys) -> str:
    capsys.readouterr()
    assert main(["load"]) == 0
    return capsys.readouterr().out


def task_path(repo: Path) -> Path:
    return sibling(repo, ".memory") / "proposals" / "migrate-followups.md"


def test_a_rerun_does_not_report_the_candidates_again(repo, capsys):
    old_layout(repo)
    first = migrate(capsys, "--yes")
    assert "candidate(s) from" in first
    again = migrate(capsys, "--yes")
    assert "candidate" not in again.lower()
    assert "worklist" not in again.lower()
    assert "Agents connected" not in again


def test_a_rerun_with_items_left_names_the_task_and_stays_pending(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    again = migrate(capsys, "--yes")
    assert "Migration not finished" in again
    assert str(task_path(repo)) in again
    assert task_path(repo).read_text().startswith("# Migration follow-up (pending)")


def test_a_finished_migration_ends_and_prints_nothing_in_the_load(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    assert "Migration follow-up pending" in load(capsys)
    fix_every_item(repo)
    plan = migrate(capsys)
    assert "Migration finished" in plan
    assert task_path(repo).is_file(), "the plan changes nothing"
    assert "Migration finished" in migrate(capsys, "--yes")
    assert not task_path(repo).exists()
    assert "igration" not in load(capsys)


def test_a_rerun_after_the_end_changes_nothing_and_says_so(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    fix_every_item(repo)
    migrate(capsys, "--yes")
    before = snapshot(repo.parent)
    assert "Migration finished" in migrate(capsys, "--yes")
    assert snapshot(repo.parent) == before


def test_a_deleted_task_stays_deleted(repo, capsys):
    """A line that must stay (a shared file, or history) needs a way to end the migration."""
    old_layout(repo)
    migrate(capsys, "--yes")
    task_path(repo).unlink()
    assert "Migration finished" in migrate(capsys, "--yes")
    assert not task_path(repo).exists()
    assert "igration" not in load(capsys)


def test_the_task_gives_the_agent_one_end_and_a_way_to_leave_a_line(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    task = task_path(repo).read_text()
    done = task[task.index("## Done when") :]
    assert "`memory migrate --yes`" in done
    assert "delete this file" in done
    assert "grep" not in task
    assert "team's OK" not in task


def test_the_task_first_line_counts_the_items(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    first = task_path(repo).read_text().splitlines()[0]
    assert first == "# Migration follow-up (pending): 7 item(s)"


def test_a_doc_named_for_the_old_folder_may_be_rewritten_in_place(repo, capsys):
    """The task offers a rewrite, so a rewrite must pass, and a line that names the doc too."""
    old_layout(repo)
    migrate(capsys, "--yes")
    write(repo / "docs" / "working" / "memory-bank.md", "# Memory\nRun `memory load`.\n")
    write(repo / "CLAUDE.md", "See docs/working/memory-bank.md for how it works.\n")
    write(repo / ".claude" / "settings.json", '{"hooks":{}}\n')
    assert "Migration finished" in migrate(capsys, "--yes")


@pytest.mark.parametrize("found", ["pstack skills: missing for Codex. Run: x"])
def test_the_done_test_asks_for_no_skills(repo, capsys, monkeypatch, found):
    monkeypatch.setattr(skills, "advisory", lambda tools=None: found)
    old_layout(repo)
    migrate(capsys, "--yes")
    task = task_path(repo).read_text()
    assert "pstack" not in task
    assert "memory skills status" not in task
    fix_every_item(repo)
    assert "Migration finished" in migrate(capsys, "--yes")
