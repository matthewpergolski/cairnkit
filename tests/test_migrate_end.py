"""A migration of a real prose folder has one end, and it leaves one active copy of each file."""

from pathlib import Path

from conftest import add_worktree, git
from test_migrate import sibling, snapshot

from cairnkit import adapters, hooks_cmd, skills
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
    assert "Migration" not in load(capsys)


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
    assert "Migration" not in load(capsys)


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


def test_the_done_test_asks_for_no_skills(repo, capsys, monkeypatch):
    monkeypatch.setattr(skills, "advisory", lambda tools=None: "pstack skills: missing. Run: x")
    old_layout(repo)
    migrate(capsys, "--yes")
    task = task_path(repo).read_text()
    assert "pstack" not in task
    assert "memory skills status" not in task
    fix_every_item(repo)
    assert "Migration finished" in migrate(capsys, "--yes")


# --- one active copy of each file -----------------------------------------------------


def memdir(repo: Path) -> Path:
    return sibling(repo, ".memory")


def half_moved(repo: Path) -> Path:
    """An old folder with both layouts, and the two status files disagree."""
    old_layout(repo)
    write(repo / "memory-bank" / "notes" / "status.md", "# Status\nPR 96 merged. Open: 97.\n")
    return repo


def test_an_old_notes_folder_is_not_nested_and_its_file_wins(repo, capsys):
    half_moved(repo)
    migrate(capsys, "--yes")
    mem = memdir(repo)
    assert "PR 96 merged" in (mem / "notes" / "status.md").read_text()
    assert not (mem / "notes" / "notes").exists()
    out = load(capsys)
    assert "PR 96 merged" in out
    assert "Do not merge" not in out


def test_the_copy_that_lost_is_kept_and_is_a_task_for_the_agent(repo, capsys):
    half_moved(repo)
    migrate(capsys, "--yes")
    copy = memdir(repo) / "proposals" / "old-copies" / "status.md"
    assert "Do not merge" in copy.read_text()
    task = task_path(repo).read_text()
    assert "`memory-bank/proposals/old-copies/status.md:2`" in task
    assert "memory-bank/notes/status.md" in task


def test_deleting_the_old_copy_closes_its_item(repo, capsys):
    half_moved(repo)
    migrate(capsys, "--yes")
    fix_every_item(repo)
    assert "Migration not finished: 1 item(s)" in migrate(capsys, "--yes")
    (memdir(repo) / "proposals" / "old-copies" / "status.md").unlink()
    assert "Migration finished" in migrate(capsys, "--yes")


def test_a_note_that_differs_from_the_old_file_gets_the_same_task(repo, capsys):
    old_layout(repo)
    write(memdir(repo) / "notes" / "log.md", "# Log\nA newer log.\n")
    (memdir(repo) / "facts").mkdir()
    migrate(capsys, "--yes")
    assert (memdir(repo) / "notes" / "log.md").read_text() == "# Log\nA newer log.\n"
    assert "`memory-bank/proposals/old-copies/log.md:2`" in task_path(repo).read_text()


def test_a_candidate_in_an_old_notes_folder_points_at_the_note(repo, capsys):
    old_layout(repo)
    write(repo / "memory-bank" / "notes" / "traps.md", "# Traps\n- Never run pip.\n")
    migrate(capsys, "--yes")
    text = (memdir(repo) / "proposals" / "migrate-candidates.jsonl").read_text()
    assert "file:memory-bank/notes/traps.md:2" in text
    assert "notes/notes" not in text


def test_the_old_path_that_a_doc_names_holds_only_a_pointer(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    pointer = (repo / "memory-bank" / "status.md").read_text()
    assert "memory-bank/notes/status.md" in pointer
    assert "Do not merge" not in pointer
    assert not (repo / "memory-bank" / "decisions.md").exists(), "no doc names it"


def test_the_pointer_goes_when_no_doc_names_the_path(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    fix_every_item(repo)
    migrate(capsys, "--yes")
    assert not (memdir(repo) / "status.md").exists()


def test_the_pointer_stays_for_a_line_that_stays(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    task_path(repo).unlink()
    migrate(capsys, "--yes")
    assert "memory-bank/notes/status.md" in (memdir(repo) / "status.md").read_text()


def test_a_doc_path_cannot_put_a_pointer_outside_the_memory(repo, capsys):
    old_layout(repo)
    outside = repo.parent / "outside.md"
    outside.write_text("mine\n")
    write(repo / "CLAUDE.md", "See memory-bank/notes/../../outside.md and memory-bank/../x.md\n")
    write(repo.parent / "x.md", "mine\n")
    write(repo / "CONTRIBUTING.md", "See memory-bank/../../outside.md\n")
    migrate(capsys, "--yes")
    assert outside.read_text() == "mine\n"
    assert (repo.parent / "x.md").read_text() == "mine\n"
    assert not (repo.parent.parent / "outside.md").exists()


def test_a_status_file_written_to_the_old_path_later_is_moved_away(repo, capsys):
    """Old instructions lead an agent to write there, and that is how two copies come back."""
    old_layout(repo)
    migrate(capsys, "--yes")
    fix_every_item(repo)
    migrate(capsys, "--yes")
    write(repo / "memory-bank" / "status.md", "# Status\nA later status.\n")
    out = migrate(capsys, "--yes")
    assert "Migration not finished: 1 item(s)" in out
    assert not (memdir(repo) / "status.md").exists()
    assert "A later status" in (memdir(repo) / "proposals" / "old-copies" / "status.md").read_text()
    assert "Do not merge" in (memdir(repo) / "notes" / "status.md").read_text()


def test_a_later_file_with_no_note_moves_into_notes(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    write(repo / "memory-bank" / "specs" / "new.md", "# New\n")
    migrate(capsys, "--yes")
    assert not (memdir(repo) / "specs").exists()
    assert (memdir(repo) / "notes" / "specs" / "new.md").read_text() == "# New\n"


def test_a_later_file_with_the_same_text_as_the_note_is_removed(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    write(memdir(repo) / "log.md", (memdir(repo) / "notes" / "log.md").read_text())
    migrate(capsys, "--yes")
    assert "old-copies/log.md" not in task_path(repo).read_text()
    assert "memory-bank/notes/log.md" in (memdir(repo) / "log.md").read_text(), "a doc names it"


def test_a_repo_already_half_moved_with_no_old_folder_gets_settled(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    old = sibling(repo, ".memory-old")
    for path in sorted(old.rglob("*"), reverse=True):
        path.rmdir() if path.is_dir() else path.unlink()
    old.rmdir()
    (memdir(repo) / "proposals" / "migrate-candidates.jsonl").unlink()
    write(repo / "memory-bank" / "status.md", "# Status\nStale.\n")
    assert "Migration not finished" in migrate(capsys, "--yes")
    assert "Stale" in (memdir(repo) / "proposals" / "old-copies" / "status.md").read_text()
    assert "memory-bank/notes/status.md" in (memdir(repo) / "status.md").read_text()


def test_the_plan_of_a_rerun_moves_nothing(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    write(repo / "memory-bank" / "status.md", "# Status\nA later status.\n")
    before = snapshot(repo.parent)
    out = migrate(capsys)
    assert "would" in out
    assert snapshot(repo.parent) == before


# --- what the old tooling did -----------------------------------------------------------


NAMED_CHECKS = (
    "secret scan",
    "status older than the code",
    "worktree not in queue",
    "file pointers",
    "note limits",
    "check_changelog_entry",
)


def test_the_plan_and_the_run_list_each_old_check_by_name(repo, capsys):
    old_layout(repo)
    for out in (migrate(capsys), migrate(capsys, "--yes")):
        for name in NAMED_CHECKS:
            assert out.count(name) == 1, name


def test_the_list_says_what_the_check_reads_and_does_not_call_the_checker_unused(repo, capsys):
    old_layout(repo)
    out = migrate(capsys, "--yes")
    assert "`memory check` reads notes and facts for secrets" in out
    assert "unused" not in out
    assert "unused" not in task_path(repo).read_text()


def test_a_rerun_does_not_list_the_checks_again(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    again = migrate(capsys, "--yes")
    for name in NAMED_CHECKS:
        assert name not in again, name


def test_the_task_holds_the_list_so_the_agent_can_tell_the_developer(repo, capsys):
    old_layout(repo)
    migrate(capsys, "--yes")
    task = task_path(repo).read_text()
    for name in NAMED_CHECKS:
        assert task.count(name) == 1, name


def test_no_old_tooling_means_no_list(repo, capsys):
    write(repo / "memory-bank" / "status.md", "# Status\n")
    write(repo / ".gitignore", ".worktrees/\nmemory-bank/\n")
    out = migrate(capsys, "--yes")
    assert "old tooling" not in out


def test_a_checker_with_no_known_check_is_named_for_the_agent_to_read(repo, capsys):
    old_layout(repo)
    write(repo / "tools" / "check_memory.py", "print('hello')\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "plain")
    assert "tools/check_memory.py: no check found by name" in migrate(capsys, "--yes")


def test_a_checker_inside_the_old_folder_is_read_too(repo, capsys):
    write(repo / "memory-bank" / "check_memory.py", "def check_secrets():\n    pass\n")
    write(repo / ".gitignore", ".worktrees/\nmemory-bank/\n")
    assert "check_memory.py: secret scan" in migrate(capsys, "--yes")


# --- which checkout, and what it installs ----------------------------------------------


def test_the_plan_from_a_worktree_says_which_checkout_it_acts_on(repo, capsys, monkeypatch):
    old_layout(repo)
    worktree = add_worktree(repo, "feature-x")
    monkeypatch.chdir(worktree)
    out = migrate(capsys)
    assert f"It acts on the main checkout {repo}" in out
    assert f"You ran it from the worktree {worktree}" in out


def test_the_plan_from_the_main_checkout_names_it_too(repo, capsys):
    old_layout(repo)
    out = migrate(capsys)
    assert f"It acts on the main checkout {repo}" in out
    assert "You ran it from the worktree" not in out


def test_a_fix_on_a_branch_counts_when_the_rerun_runs_there(repo, capsys, monkeypatch):
    old_layout(repo)
    worktree = add_worktree(repo, "feature-x")
    migrate(capsys, "--yes")
    fix_every_item(worktree)
    monkeypatch.chdir(worktree)
    assert "Migration finished" in migrate(capsys, "--yes")


def test_the_plan_names_all_that_it_installs_and_installs_only_that(repo, capsys, monkeypatch):
    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    monkeypatch.setattr(adapters, "detect", lambda project: ["claude"])
    old_layout(repo)
    worktree = add_worktree(repo, "feature-x")
    plan = migrate(capsys)
    assert "would connect the agent tools (claude)" in plan
    assert str(worktree) in plan
    hooks = repo / ".git" / "hooks"
    named = {"pre-commit", "post-checkout", "pre-push", "post-merge"}
    assert str(hooks) in plan
    for name in named:
        assert name in plan
    assert not (hooks / "pre-commit").exists()
    assert not (worktree / ".claude" / "settings.local.json").exists()
    out = migrate(capsys, "--yes")
    assert "connect the agent tools (claude)" in out
    assert (worktree / ".claude" / "settings.local.json").is_file()
    assert {p.name for p in hooks.iterdir() if not p.name.endswith(".sample")} == named
    assert git(repo, "status", "--short") == ""


def test_a_rerun_installs_nothing(repo, capsys, monkeypatch):
    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    monkeypatch.setattr(adapters, "detect", lambda project: ["claude"])
    old_layout(repo)
    migrate(capsys, "--yes")
    (repo / ".git" / "hooks" / "post-merge").unlink()
    again = migrate(capsys, "--yes")
    assert not (repo / ".git" / "hooks" / "post-merge").exists()
    assert "connect" not in again
