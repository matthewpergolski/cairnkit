"""The work-landed signal: git, not the clock, says that a fact's work is on the main branch."""

from __future__ import annotations

import re
from pathlib import Path

from conftest import git

from cairnkit import landed, paths
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project


def at(monkeypatch, day: str) -> None:
    """Facts and commits made from here on carry this date."""
    when = f"2026-10-{day}T12:00:00+00:00"
    monkeypatch.setenv("MEMORY_NOW", when)
    monkeypatch.setenv("GIT_COMMITTER_DATE", when)
    monkeypatch.setenv("GIT_AUTHOR_DATE", when)


def commit(root: Path, message: str, files: dict[str, str | None]) -> None:
    for rel, body in files.items():
        path = root / rel
        if body is None:
            git(root, "rm", "-q", str(path))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        git(root, "add", str(path))
    git(root, "commit", "-q", "-m", message)


def add(capsys, *args: str) -> str:
    capsys.readouterr()
    assert main(["add", *args]) == 0
    return re.search(r"added (f-\S+)", capsys.readouterr().out).group(1)


def found(repo: Path) -> dict:
    return landed.find(Memory.open(find_project(repo), None))


def merge(repo: Path, branch: str) -> None:
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", f"Merge {branch}", branch)


def test_files_land_when_the_branch_merges_into_main(mem, repo, capsys, monkeypatch):
    at(monkeypatch, "05")
    commit(repo, "app", {"src/app.py": "v1\n"})
    git(repo, "checkout", "-q", "-b", "feature")
    at(monkeypatch, "10")
    fid = add(capsys, "Yes to the new app layout.", "--kind", "decision", "--files", "src/app.py")
    at(monkeypatch, "11")
    commit(repo, "new layout", {"src/app.py": "v2\n"})
    assert fid not in found(repo), "the work is only on the feature branch"
    at(monkeypatch, "12")
    merge(repo, "feature")
    evidence = found(repo)[fid]
    assert evidence.date == "2026-10-12"
    assert evidence.subject == "Merge feature"
    assert evidence.commit == git(repo, "rev-parse", "--short", "HEAD").strip()


def test_a_commit_before_the_fact_is_no_landing(mem, repo, capsys, monkeypatch):
    at(monkeypatch, "05")
    commit(repo, "app", {"src/app.py": "v1\n"})
    at(monkeypatch, "10")
    fid = add(capsys, "Yes to the app work.", "--kind", "decision", "--files", "src/app.py")
    assert fid not in found(repo)


def test_every_named_path_must_land(mem, repo, capsys, monkeypatch):
    at(monkeypatch, "05")
    commit(repo, "base", {"src/app.py": "v1\n", "docs/plan.md": "plan\n"})
    at(monkeypatch, "10")
    fid = add(
        capsys,
        "Owner approved the change to src/app.py and docs/plan.md, and/or more, e.g. tests.",
        "--kind",
        "rule",
        "--basis",
        "seen",
    )
    at(monkeypatch, "11")
    commit(repo, "app only", {"src/app.py": "v2\n"})
    assert fid not in found(repo), "docs/plan.md has no commit after the fact"
    at(monkeypatch, "12")
    commit(repo, "plan", {"docs/plan.md": "plan 2\n"})
    assert found(repo)[fid].date == "2026-10-12"


def test_a_deleted_path_lands_by_its_removal(mem, repo, capsys, monkeypatch):
    at(monkeypatch, "05")
    commit(repo, "old", {"src/old.py": "x\n"})
    at(monkeypatch, "10")
    fid = add(capsys, "Remove src/old.py.", "--kind", "decision", "--basis", "seen")
    at(monkeypatch, "11")
    commit(repo, "remove old", {"src/old.py": None})
    assert found(repo)[fid].subject == "remove old"


def test_a_fact_that_names_no_path_never_lands(mem, repo, capsys, monkeypatch):
    at(monkeypatch, "10")
    fid = add(capsys, "Yes to migration 0018.", "--kind", "decision", "--basis", "seen")
    at(monkeypatch, "11")
    commit(repo, "migration", {"db/m0018.sql": "create\n"})
    assert fid not in found(repo)


def test_work_lands_on_the_integration_branch_too(mem, repo, capsys, monkeypatch):
    at(monkeypatch, "05")
    git(repo, "checkout", "-q", "-b", "dev")
    git(repo, "checkout", "-q", "-b", "feature")
    at(monkeypatch, "10")
    fid = add(capsys, "Go ahead with it.", "--kind", "decision", "--files", "src/new.py")
    at(monkeypatch, "11")
    commit(repo, "new", {"src/new.py": "x\n"})
    assert fid not in found(repo)
    git(repo, "checkout", "-q", "dev")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge feature into dev", "feature")
    assert found(repo)[fid].subject == "Merge feature into dev"


def test_a_change_after_the_landing_counts_as_a_review(mem, repo, capsys, monkeypatch):
    at(monkeypatch, "10")
    fid = add(capsys, "Keep src/app.py small.", "--kind", "decision", "--files", "src/app.py")
    at(monkeypatch, "11")
    commit(repo, "app", {"src/app.py": "v1\n"})
    assert fid in found(repo)
    at(monkeypatch, "12")
    assert main(["change", fid, "--status", "active", "--reason", "Still applies."]) == 0
    assert fid not in found(repo), "the agent looked after the commit"


def test_one_git_log_for_all_facts_and_none_from_the_cache(mem, repo, capsys, monkeypatch):
    at(monkeypatch, "10")
    ids = [
        add(capsys, f"Yes to part {n}.", "--kind", "decision", "--files", f"src/p{n}.py")
        for n in range(5)
    ]
    at(monkeypatch, "11")
    commit(repo, "parts", {f"src/p{n}.py": "x\n" for n in range(5)})
    logs = []
    real = paths.run_git

    def counted(cwd, *args, **kwargs):
        if "log" in args:
            logs.append(args)
        return real(cwd, *args, **kwargs)

    monkeypatch.setattr(landed, "run_git", counted)
    assert set(found(repo)) == set(ids)
    assert len(logs) == 1
    assert set(found(repo)) == set(ids)
    assert len(logs) == 1, "the second read comes from the cache"
    at(monkeypatch, "12")
    commit(repo, "more", {"src/p0.py": "y\n"})
    found(repo)
    assert len(logs) == 2, "a moved main branch reads git again"
