"""memory migrate --fix-references: references, hooks and the follow-up task."""

import json
from pathlib import Path

from conftest import git
from test_migrate import old_repo, sibling, snapshot, write_old

from cairnkit.cli import main

CLAUDE = (
    "Notes live in `memory-bank/status.md` and `memory-bank/howto/python.md`.\n"
    "Run `uv run tools/check_memory.py` at the start of a session.\n"
    "Read docs/working/memory-bank.md before you write a note.\n"
    "`memory-bank/` is local and ignored by git.\n"
)
GUIDE = "See memory-bank/decisions.md.\n```\ncat memory-bank/brief.md\n```\n"
OLD_HOOK = {
    "hooks": {
        "SessionStart": [
            {"hooks": [{"type": "command", "command": "uv run tools/check_memory.py || true"}]}
        ]
    }
}


def tracked_repo(repo: Path) -> Path:
    old_repo(repo)
    files = {
        "CLAUDE.md": CLAUDE,
        "AGENTS.md": "agents\n",
        "docs/guide.md": GUIDE,
        "docs/working/memory-bank.md": "# Old notes doc\n",
        "tools/check_memory.py": "print('old checker')\n",
        ".claude/settings.json": json.dumps(OLD_HOOK, indent=2) + "\n",
    }
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "docs")
    return repo


def migrate(*args: str) -> int:
    return main(["migrate", "--preset", "none", *args])


def test_plan_shows_the_references_and_changes_nothing(repo, capsys):
    tracked_repo(repo)
    before = snapshot(repo.parent)
    assert migrate("--fix-references") == 0
    out = capsys.readouterr().out
    assert "CLAUDE.md (tracked by git): 2 path(s)" in out
    assert "docs/guide.md (tracked by git): 2 path(s)" in out
    assert "memory migrate --fix-references --yes" in out
    assert snapshot(repo.parent) == before


def test_plan_without_the_flag_says_how_many_it_would_fix(repo, capsys):
    tracked_repo(repo)
    assert migrate() == 0
    out = capsys.readouterr().out
    assert "4 path(s) in 2 file(s) name the old layout" in out
    assert "--fix-references" in out


def test_yes_without_the_flag_leaves_the_files_alone(repo, capsys):
    tracked_repo(repo)
    assert migrate("--yes") == 0
    assert (repo / "CLAUDE.md").read_text() == CLAUDE
    assert git(repo, "status", "--porcelain") == ""
    followups = (sibling(repo, ".memory") / "proposals" / "migrate-followups.md").read_text()
    assert "memory migrate --fix-references --yes" in followups


def test_fix_references_rewrites_the_working_tree_and_commits_nothing(repo, capsys):
    tracked_repo(repo)
    head = git(repo, "rev-parse", "HEAD")
    assert migrate("--yes", "--fix-references") == 0
    out = capsys.readouterr().out
    assert "memory-bank/notes/status.md" in (repo / "CLAUDE.md").read_text()
    assert "memory-bank/notes/howto/python.md" in (repo / "CLAUDE.md").read_text()
    assert (repo / "docs" / "guide.md").read_text() == (
        "See memory-bank/notes/decisions.md.\n```\ncat memory-bank/notes/brief.md\n```\n"
    )
    assert (repo / "AGENTS.md").read_text() == "agents\n"
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "diff", "--cached", "--name-only") == ""
    changed = git(repo, "diff", "--name-only").split()
    assert sorted(changed) == ["CLAUDE.md", "docs/guide.md"]
    assert "CLAUDE.md" in out and "2 files changed" in out  # the diffstat


def test_fix_references_twice_changes_nothing_more(repo, capsys):
    tracked_repo(repo)
    assert migrate("--yes", "--fix-references") == 0
    before = snapshot(repo.parent)
    capsys.readouterr()
    assert migrate("--yes", "--fix-references") == 0
    assert "no old paths to rewrite" in capsys.readouterr().out.lower()
    assert snapshot(repo.parent) == before


def test_fix_references_after_a_plain_migrate(repo):
    tracked_repo(repo)
    assert migrate("--yes") == 0
    assert migrate("--yes", "--fix-references") == 0
    assert "memory-bank/notes/status.md" in (repo / "CLAUDE.md").read_text()


def test_hooks_are_installed_and_the_tracked_old_hook_is_left_alone(repo, capsys):
    tracked_repo(repo)
    assert migrate("--yes", "--fix-references") == 0
    out = capsys.readouterr().out
    assert (repo / ".claude" / "settings.json").read_text() == json.dumps(OLD_HOOK, indent=2) + "\n"
    local = json.loads((repo / ".claude" / "settings.local.json").read_text())
    assert "cairnkit hook" in json.dumps(local)
    assert "tools/check_memory.py" in out  # the old checker is named
    assert (repo / "tools" / "check_memory.py").read_text() == "print('old checker')\n"
    assert "not deleted" in out and "unused" in out


def test_plan_names_the_old_hook_and_the_hooks_it_would_add(repo, capsys):
    tracked_repo(repo)
    before = snapshot(repo.parent)
    assert migrate("--fix-references") == 0
    out = capsys.readouterr().out
    assert ".claude/settings.json" in out and "SessionStart" in out
    assert "settings.local.json" in out
    assert snapshot(repo.parent) == before


def test_no_hook_step_when_no_hook_runs_the_old_checker(repo):
    old_repo(repo)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text("{}\n")
    assert migrate("--yes", "--fix-references") == 0
    assert not (repo / ".claude" / "settings.local.json").exists()


def test_followup_file_lists_each_line_with_a_suggestion_and_the_acceptance_check(repo, capsys):
    tracked_repo(repo)
    assert migrate("--yes", "--fix-references") == 0
    out = capsys.readouterr().out
    path = sibling(repo, ".memory") / "proposals" / "migrate-followups.md"
    assert str(path) in out or "memory-bank/proposals/migrate-followups.md" in out
    text = path.read_text()
    assert text.startswith("# Migration follow-up (pending)")
    assert "CLAUDE.md:2" in text and "memory check" in text
    assert "CLAUDE.md:3" in text
    assert "docs/working/memory-bank.md:1" in text
    assert ".claude/settings.json" in text and "SessionStart" in text
    assert "tools/check_memory.py" in text and "unused" in text
    assert "grep -nE" in text and "check[_-]?memory" in text
    assert "memory check" in text.split("Done when")[1]
    # Nothing that the rewrite fixed is listed.
    assert "CLAUDE.md:1" not in text and "docs/guide.md" not in text


def test_followup_file_is_stable_on_a_rerun(repo):
    tracked_repo(repo)
    assert migrate("--yes", "--fix-references") == 0
    path = sibling(repo, ".memory") / "proposals" / "migrate-followups.md"
    first = path.read_text()
    assert migrate("--yes", "--fix-references") == 0
    assert path.read_text() == first


def test_no_followup_file_when_nothing_is_left(repo, capsys):
    old_repo(repo)
    (repo / "CLAUDE.md").write_text("Notes: memory-bank/status.md\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "doc")
    assert migrate("--yes", "--fix-references") == 0
    assert not (sibling(repo, ".memory") / "proposals" / "migrate-followups.md").exists()
    assert "follow-up" not in capsys.readouterr().out.lower().replace("memory-bank", "")


def test_followup_becomes_done_when_the_lines_are_fixed(repo):
    tracked_repo(repo)
    assert migrate("--yes", "--fix-references") == 0
    (repo / "CLAUDE.md").write_text("Run `memory check`.\n")
    (repo / "docs" / "working" / "memory-bank.md").unlink()
    (repo / ".claude" / "settings.json").write_text("{}\n")
    (repo / "tools" / "check_memory.py").unlink()
    assert migrate("--yes", "--fix-references") == 0
    text = (sibling(repo, ".memory") / "proposals" / "migrate-followups.md").read_text()
    assert text.startswith("# Migration follow-up (done)")


def test_load_shows_one_line_while_the_followup_is_pending(repo, capsys):
    tracked_repo(repo)
    assert migrate("--yes", "--fix-references") == 0
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "Migration follow-up pending: see memory-bank/proposals/migrate-followups.md" in out
    assert out.count("Migration follow-up") == 1


def test_load_is_quiet_when_the_followup_is_done_or_absent(repo, capsys):
    old_repo(repo)
    assert migrate("--yes") == 0
    folder = sibling(repo, ".memory") / "proposals"
    capsys.readouterr()
    main(["load"])
    assert "Migration follow-up" not in capsys.readouterr().out
    (folder / "migrate-followups.md").write_text("# Migration follow-up (done)\n")
    main(["load"])
    assert "Migration follow-up" not in capsys.readouterr().out


def test_hooks_go_only_to_the_agent_whose_hook_runs_the_old_checker(repo, monkeypatch):
    tracked_repo(repo)
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")  # every tool looks installed
    assert migrate("--yes", "--fix-references") == 0
    assert (repo / ".claude" / "settings.local.json").is_file()
    assert not (repo / ".codex").exists() and not (repo / ".cursor").exists()


def test_references_are_not_rewritten_when_the_old_folder_is_not_memory_bank(repo, capsys):
    write_old(repo / "agent-notes", {"a.md": "# A\n\n- one\n"})
    (repo / "CLAUDE.md").write_text("A different memory-bank/a.md is named here.\n")
    (repo / ".gitignore").write_text(".worktrees/\nagent-notes/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "docs")
    assert migrate("--yes", "--fix-references", "--from", "agent-notes") == 0
    out = capsys.readouterr().out
    assert (repo / "CLAUDE.md").read_text() == "A different memory-bank/a.md is named here.\n"
    assert "apply only to the memory-bank folder" in out
    assert not (sibling(repo, ".memory") / "proposals" / "migrate-followups.md").exists()


def test_plan_says_when_a_tracked_file_already_has_changes(repo, capsys):
    tracked_repo(repo)
    (repo / "CLAUDE.md").write_text(CLAUDE + "My own edit.\n")
    assert migrate("--fix-references") == 0
    out = capsys.readouterr().out
    assert "CLAUDE.md (tracked by git, already modified): 2 path(s)" in out
    assert "docs/guide.md (tracked by git): 2 path(s)" in out
