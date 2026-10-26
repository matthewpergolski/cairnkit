import json
import os
from pathlib import Path

import pytest
from conftest import add_worktree, git

from cairnkit.cli import build_parser, main

OLD_FILES = {
    "brief.md": "# Brief\n\n- Python runs through uv.\n- No AI trailers.\n",
    "decisions.md": (
        "# Decisions\n\n- 2026-10-09 The stack is Django.\n- 2026-10-10 Tests run with pytest.\n"
    ),
    "decisions-archive.md": (
        "# Decisions that left\n\n"
        "- 2026-10-09 Start small. (superseded 2026-10-10: skills came over)\n"
    ),
    "log.md": "# Log\n\n- 2026-10-09 The venv was rebuilt.\n",
    "status.md": "# Status\n\nThe app runs.\n",
    "howto/python.md": "# Python\n\n## Traps\n\n- Never run pip.\n",
}


def sibling(repo: Path, suffix: str) -> Path:
    return repo.parent / f"proj{suffix}"


def snapshot(root: Path) -> dict[str, str]:
    seen = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            if name.endswith(".lock"):  # git may start a background job in the repo
                continue
            rel = str(path.relative_to(root))
            if path.is_symlink():
                seen[rel] = "link:" + os.readlink(path)
            elif path.is_file():
                seen[rel] = path.read_bytes().hex()
            else:
                seen[rel] = "dir"
    return seen


def write_old(folder: Path, files: dict[str, str] = OLD_FILES) -> None:
    for rel, text in files.items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def old_repo(repo: Path) -> Path:
    """A repo whose `memory-bank/` is a real folder that git ignores."""
    (repo / ".gitignore").write_text(".worktrees/\nmemory-bank/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "ignore")
    write_old(repo / "memory-bank")
    return repo


def run_migrate(*args: str) -> int:
    """Run for real (--yes), unless the test asks for the plan only."""
    flags = [] if "--plan" in args else ["--yes"]
    return main(["migrate", "--preset", "none", *flags, *[a for a in args if a != "--plan"]])


def test_help_lists_migrate_and_yes(capsys):
    assert "migrate" in build_parser().format_help()
    with pytest.raises(SystemExit):
        build_parser().parse_args(["migrate", "--help"])
    assert "--yes" in capsys.readouterr().out


def test_no_flag_changes_nothing_and_says_to_rerun_with_yes(repo, capsys):
    old_repo(repo)
    before = snapshot(repo.parent)
    assert main(["migrate", "--preset", "none"]) == 0
    out = capsys.readouterr().out
    assert "memory migrate --yes" in out
    assert "would move" in out
    assert "decisions.md" in out
    assert snapshot(repo.parent) == before


def test_dry_run_is_an_explicit_alias_of_the_default(repo, capsys):
    old_repo(repo)
    before = snapshot(repo.parent)
    assert main(["migrate", "--preset", "none", "--dry-run"]) == 0
    assert "memory migrate --yes" in capsys.readouterr().out
    assert snapshot(repo.parent) == before


def test_dry_run_with_yes_is_refused(repo, capsys):
    old_repo(repo)
    before = snapshot(repo.parent)
    assert main(["migrate", "--preset", "none", "--dry-run", "--yes"]) == 1
    assert "contradict" in capsys.readouterr().err.lower()
    assert snapshot(repo.parent) == before


def test_yes_runs_for_real(repo, capsys):
    old_repo(repo)
    assert main(["migrate", "--preset", "none", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "memory migrate --yes" not in out
    assert (repo / "memory-bank").is_symlink()
    assert (sibling(repo, ".memory-old") / "decisions.md").is_file()


def test_refuses_when_there_is_nothing_to_migrate(repo, capsys):
    before = snapshot(repo.parent)
    assert run_migrate() == 1
    assert "nothing to migrate" in capsys.readouterr().err.lower()
    assert snapshot(repo.parent) == before
    (repo / "memory-bank").mkdir()
    before = snapshot(repo.parent)
    assert run_migrate() == 1
    assert snapshot(repo.parent) == before


def test_refuses_when_the_old_folder_target_exists(repo, capsys):
    old_repo(repo)
    sibling(repo, ".memory-old").mkdir()
    before = snapshot(repo.parent)
    assert run_migrate() == 1
    assert "exists" in capsys.readouterr().err
    assert snapshot(repo.parent) == before


def test_moves_the_old_folder_and_deletes_nothing(repo):
    old_repo(repo)
    assert run_migrate() == 0
    holder = sibling(repo, ".memory-old")
    for rel, text in OLD_FILES.items():
        assert (holder / rel).read_text() == text
    link = repo / "memory-bank"
    assert link.is_symlink()
    assert link.resolve() == sibling(repo, ".memory").resolve()


def test_copies_the_prose_into_notes_with_the_same_paths(repo):
    old_repo(repo)
    assert run_migrate() == 0
    notes = sibling(repo, ".memory") / "notes"
    for rel, text in OLD_FILES.items():
        assert (notes / rel).read_text() == text  # status.md replaces the placeholder
    assert (repo / "memory-bank" / "notes" / "decisions.md").is_file()


def test_writes_candidates_and_no_facts(repo, capsys):
    old_repo(repo)
    assert run_migrate() == 0
    out = capsys.readouterr().out
    mem = sibling(repo, ".memory")
    lines = [
        json.loads(line)
        for line in (mem / "proposals" / "migrate-candidates.jsonl").read_text().splitlines()
    ]
    summary, found = lines[0], lines[1:]
    assert summary["type"] == "summary"
    assert summary["candidates"] == len(found) == 7
    assert summary["files"]["decisions.md"]["candidates"] == 2
    assert summary["files"]["howto/python.md"]["candidates"] == 1
    first = next(c for c in found if c["file"] == "decisions.md")
    assert first["type"] == "candidate"
    assert first["line"] == 3 and first["suggested_kind"] == "decision"
    assert first["tier"] == "likely"
    assert summary["tiers"] == {"likely": 7, "maybe": 0, "worktree-only": 0}
    assert summary["hints"] == {"superseded": 1}
    assert first["source"] == "file:memory-bank/notes/decisions.md:3"
    assert "7 candidate" in out
    assert "7 likely" in out and "0 maybe" in out
    assert not list((mem / "facts").glob("*.jsonl")) or all(
        not p.read_text().strip() for p in (mem / "facts").glob("*.jsonl")
    )


def test_runs_check_and_reports_ok(repo, capsys):
    old_repo(repo)
    assert run_migrate() == 0
    assert "memory check: ok" in capsys.readouterr().out


def test_preset_rules_are_added_as_init_does(repo):
    old_repo(repo)
    assert main(["migrate", "--yes", "--preset", "commits"]) == 0
    facts = sibling(repo, ".memory") / "facts"
    assert sum(len(p.read_text().splitlines()) for p in facts.glob("*.jsonl")) == 3


def test_rerun_after_a_full_run_changes_nothing(repo, capsys):
    old_repo(repo)
    assert run_migrate() == 0
    before = snapshot(repo.parent)
    capsys.readouterr()
    assert run_migrate() == 0
    assert "nothing to do" in capsys.readouterr().out.lower()
    assert snapshot(repo.parent) == before


def test_rerun_after_a_partial_run_finishes_the_job(repo):
    old_repo(repo)
    os.rename(repo / "memory-bank", sibling(repo, ".memory-old"))  # the move, then a crash
    assert run_migrate() == 0
    mem = sibling(repo, ".memory")
    assert (mem / "notes" / "decisions.md").is_file()
    assert (mem / "proposals" / "migrate-candidates.jsonl").is_file()
    assert (repo / "memory-bank").resolve() == mem.resolve()


def test_rerun_never_overwrites_a_note_that_was_edited(repo, capsys):
    old_repo(repo)
    assert run_migrate() == 0
    note = sibling(repo, ".memory") / "notes" / "decisions.md"
    note.write_text("edited\n")
    assert run_migrate() == 0
    assert note.read_text() == "edited\n"
    assert "differs" in capsys.readouterr().out


def test_tracked_old_folder_is_refused_without_untrack(repo, capsys):
    (repo / "memory-bank").mkdir()
    write_old(repo / "memory-bank")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "tracked notes")
    before = snapshot(repo.parent)
    assert run_migrate() == 1
    assert "--untrack" in capsys.readouterr().err
    assert snapshot(repo.parent) == before


def test_untrack_removes_from_the_index_and_commits_nothing(repo):
    (repo / "memory-bank").mkdir()
    write_old(repo / "memory-bank")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "tracked notes")
    head = git(repo, "rev-parse", "HEAD")
    assert run_migrate("--untrack") == 0
    assert git(repo, "ls-files", "memory-bank") == ""
    staged = git(repo, "diff", "--cached", "--name-status")
    assert "D\tmemory-bank/decisions.md" in staged
    assert git(repo, "rev-parse", "HEAD") == head
    assert (sibling(repo, ".memory-old") / "decisions.md").is_file()


def test_untrack_does_nothing_for_an_ignored_folder(repo):
    old_repo(repo)
    staged_before = git(repo, "diff", "--cached", "--name-status")
    assert run_migrate("--untrack") == 0
    assert git(repo, "diff", "--cached", "--name-status") == staged_before


def test_rules_files_and_tracked_files_stay_without_the_fix_flag(repo, capsys):
    old_repo(repo)
    (repo / "CLAUDE.md").write_text("Notes: `memory-bank/status.md`. Run tools/check_memory.py.\n")
    (repo / "AGENTS.md").write_text("agents\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "rules")
    assert run_migrate() == 0
    out = capsys.readouterr().out
    assert (repo / "CLAUDE.md").read_text().startswith("Notes: `memory-bank/status.md`")
    assert (repo / "AGENTS.md").read_text() == "agents\n"
    assert git(repo, "status", "--porcelain") == ""
    assert "1 path(s) in 1 file(s) name the old layout" in out
    followups = sibling(repo, ".memory") / "proposals" / "migrate-followups.md"
    assert "CLAUDE.md:1" in followups.read_text()


def test_other_checkout_with_its_own_old_folder_is_moved_aside(repo, capsys):
    old_repo(repo)
    wt = add_worktree(repo, "feature-x")
    write_old(wt / "memory-bank", {**OLD_FILES, "decisions.md": "# Decisions\n\n- newer\n"})
    assert run_migrate() == 0
    out = capsys.readouterr().out
    aside = sibling(repo, ".memory-old.feature-x")
    assert (aside / "decisions.md").read_text() == "# Decisions\n\n- newer\n"
    assert (wt / "memory-bank").resolve() == sibling(repo, ".memory").resolve()
    assert "1 file(s) differ" in out


def test_other_checkout_target_that_exists_is_refused(repo):
    old_repo(repo)
    wt = add_worktree(repo, "feature-x")
    write_old(wt / "memory-bank")
    sibling(repo, ".memory-old.feature-x").mkdir()
    before = snapshot(repo.parent)
    assert run_migrate() == 1
    assert snapshot(repo.parent) == before


def test_from_folder_with_the_link_slot_free(repo):
    write_old(repo / "agent-notes", {"a.md": "# A\n\n- one\n"})
    (repo / ".gitignore").write_text(".worktrees/\nagent-notes/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "ignore")
    assert main(["migrate", "--yes", "--preset", "none", "--from", "agent-notes"]) == 0
    assert (sibling(repo, ".memory-old") / "a.md").is_file()
    assert (sibling(repo, ".memory") / "notes" / "a.md").is_file()
    assert not (repo / "agent-notes").exists()


def test_path_flag_sets_the_memory_folder(repo, tmp_path):
    old_repo(repo)
    target = tmp_path / "elsewhere" / "mem"
    assert main(["migrate", "--yes", "--preset", "none", "--path", str(target)]) == 0
    assert (target / "notes" / "decisions.md").is_file()
    assert (repo / "memory-bank").resolve() == target.resolve()


def test_migrate_works_outside_git(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    write_old(plain / "memory-bank")
    monkeypatch.chdir(plain)
    assert main(["migrate", "--yes", "--preset", "none"]) == 0
    assert (tmp_path / "plain.memory" / "notes" / "decisions.md").is_file()
    assert (tmp_path / "plain.memory-old" / "decisions.md").is_file()


def worktree_repo(repo: Path) -> tuple[Path, Path]:
    """The main folder, and a worktree whose own old folder has 3 lines the main one lacks."""
    old_repo(repo)
    wt = add_worktree(repo, "feature-x")
    extra = OLD_FILES["decisions.md"] + "- 2026-10-12 Only in the worktree.\n"
    write_old(
        wt / "memory-bank",
        {**OLD_FILES, "decisions.md": extra, "specs/x.md": "# X\n\n- one\n- two\n"},
    )
    return repo, wt


def read_worklist(repo: Path) -> list[dict]:
    path = sibling(repo, ".memory") / "proposals" / "migrate-candidates.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_worktree_only_lines_join_the_worklist(repo, capsys):
    worktree_repo(repo)
    assert run_migrate() == 0
    out = capsys.readouterr().out
    rows = read_worklist(repo)
    summary, found = rows[0], rows[1:]
    only = [c for c in found if c.get("from_worktree") == "feature-x"]
    assert sorted((c["file"], c["line"]) for c in only) == [
        ("decisions.md", 5),
        ("specs/x.md", 3),
        ("specs/x.md", 4),
    ]
    assert {c["tier"] for c in only} == {"worktree-only"}
    aside = sibling(repo, ".memory-old.feature-x")
    first = next(c for c in only if c["file"] == "decisions.md")
    assert first["text"] == "2026-10-12 Only in the worktree."
    assert first["source"] == f"file:{aside}/decisions.md:5"
    assert (aside / "decisions.md").read_text().splitlines()[4].endswith("the worktree.")
    assert summary["worktree_only"] == {"feature-x": 3}
    assert summary["tiers"]["worktree-only"] == 3
    assert "3 worktree-only line(s) from feature-x" in out
    # Lines that the main copy has are not repeated.
    assert not any(c["text"] == "Never run pip." for c in only)


def test_plan_counts_worktree_only_lines_and_changes_nothing(repo, capsys):
    worktree_repo(repo)
    before = snapshot(repo.parent)
    assert main(["migrate", "--preset", "none"]) == 0
    out = capsys.readouterr().out
    assert "3 worktree-only line(s) from feature-x" in out
    assert snapshot(repo.parent) == before


def test_rerun_adds_no_duplicate_worktree_candidates(repo):
    worktree_repo(repo)
    assert run_migrate() == 0
    before = snapshot(repo.parent)
    assert run_migrate() == 0
    assert snapshot(repo.parent) == before
    only = [c for c in read_worklist(repo)[1:] if c.get("from_worktree")]
    assert len(only) == 3


def test_worktree_only_is_found_again_after_a_partial_run(repo):
    _, wt = worktree_repo(repo)
    os.rename(repo / "memory-bank", sibling(repo, ".memory-old"))
    os.rename(wt / "memory-bank", sibling(repo, ".memory-old.feature-x"))
    assert run_migrate() == 0
    only = [c for c in read_worklist(repo)[1:] if c.get("from_worktree")]
    assert len(only) == 3


def test_links_inside_the_old_folder_are_reported_and_kept(repo, capsys):
    old_repo(repo)
    (repo / "memory-bank" / "outside.md").symlink_to(repo / "README.md")
    assert run_migrate() == 0
    out = capsys.readouterr().out
    assert "1 link(s)" in out and "not copied" in out
    holder = sibling(repo, ".memory-old")
    assert (holder / "outside.md").is_symlink()
    assert not (sibling(repo, ".memory") / "notes" / "outside.md").exists()


def test_an_old_folder_that_is_a_link_elsewhere_is_named_in_the_refusal(repo, capsys, tmp_path):
    real = tmp_path / "elsewhere"
    write_old(real)
    (repo / "memory-bank").symlink_to(real)
    before = snapshot(repo.parent)
    assert run_migrate() == 1
    err = capsys.readouterr().err
    assert "is a link to" in err and "elsewhere" in err
    assert snapshot(repo.parent) == before


def test_lines_that_live_in_an_instruction_file_are_skipped(repo, capsys):
    old_repo(repo)
    (repo / "AGENTS.md").write_text("# Agents\n\n1. **Python.** Never run pip.\n")
    (repo / "CLAUDE.md").write_text("@AGENTS.md\n\npython runs through UV\n")
    assert run_migrate() == 0
    out = capsys.readouterr().out
    rows = read_worklist(repo)
    summary, found = rows[0], rows[1:]
    texts = [c["text"] for c in found]
    assert "Never run pip." not in texts and "Python runs through uv." not in texts
    assert summary["candidates"] == len(found) == 5
    assert summary["in_instruction_files"] == 2
    assert summary["files"]["howto/python.md"]["candidates"] == 0
    assert summary["files"]["howto/python.md"]["instructions"] == 1
    assert "2 candidate(s) skipped: an instruction file already holds them" in out


def test_the_block_that_memory_writes_is_not_a_home(repo, capsys):
    from cairnkit.instructions import block
    from cairnkit.rules import GUARDED

    old_repo(repo)
    (repo / "memory-bank" / "rules.md").write_text(f"# Rules\n\n- {GUARDED}\n")
    (repo / "AGENTS.md").write_text(f"# Agents\n\n{block()}")
    assert run_migrate() == 0
    rows = read_worklist(repo)
    assert rows[0]["in_instruction_files"] == 0
    assert GUARDED in [c["text"] for c in rows[1:]]


def test_a_start_marker_without_an_end_is_not_a_home(repo, capsys):
    from cairnkit.instructions import END, block
    from cairnkit.rules import GUARDED

    old_repo(repo)
    (repo / "memory-bank" / "rules.md").write_text(f"# Rules\n\n- {GUARDED}\n")
    (repo / "AGENTS.md").write_text("# Agents\n\n" + block().replace(END + "\n", ""))
    assert run_migrate() == 0
    rows = read_worklist(repo)
    assert rows[0]["in_instruction_files"] == 0
    assert GUARDED in [c["text"] for c in rows[1:]]


def test_a_line_inside_a_multi_line_comment_is_not_a_home(repo, capsys):
    old_repo(repo)
    (repo / "memory-bank" / "rules.md").write_text("# Rules\n\n- Never deploy on Friday.\n")
    (repo / "AGENTS.md").write_text("# Agents\n\n<!--\n- Never deploy on Friday.\n-->\n")
    assert run_migrate() == 0
    rows = read_worklist(repo)
    assert rows[0]["in_instruction_files"] == 0
    assert "Never deploy on Friday." in [c["text"] for c in rows[1:]]
