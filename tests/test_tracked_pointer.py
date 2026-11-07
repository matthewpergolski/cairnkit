"""A repo cannot choose the memory, and a memory that git tracks does not load.

`.memory-path` and the `memory-bank` link are the owner's local files. A copy that git tracks
came with the repo, from anyone who can commit to it. A memory folder that git tracks can be
written by the same people, and its rules have no author, so they would print as the owner's.
"""

from __future__ import annotations

import io
import json
import os
import shutil

import pytest
from conftest import git, make_fact, write_facts

from cairnkit.cli import main
from cairnkit.paths import find_project, plain_root, resolve_memory_dir
from cairnkit.selection import FRAME_HEADER

MARKER = "MARKER-RULE-123"


def evil_rule() -> str:
    rule = make_fact("f-20260101-0001", MARKER, kind="rule", writer="x")
    return json.dumps(rule) + "\n"


def commit_on_side(repo, files: dict[str, str]) -> None:
    git(repo, "checkout", "-q", "-b", "side")
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-f", *files)
    git(repo, "commit", "-q", "-m", "side")
    git(repo, "checkout", "-q", "main")


def session_start(capsys, monkeypatch) -> str:
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "t", "source": "startup"}'))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    return capsys.readouterr().out


def test_a_pulled_memory_path_does_not_choose_the_memory(repo, mem, capsys, monkeypatch):
    commit_on_side(repo, {".memory-path": "evil\n", "evil/facts/a.jsonl": evil_rule()})
    git(repo, "merge", "-q", "side")
    out = session_start(capsys, monkeypatch)
    assert MARKER not in out
    assert resolve_memory_dir(find_project(), None)[0] == mem
    assert ".memory-path, so the tool does not use it to find the memory" in out
    capsys.readouterr()
    main(["check"])
    assert ".memory-path, so the tool does not use it" in capsys.readouterr().out


def test_a_tracked_link_does_not_choose_the_memory(repo, tmp_path, capsys, monkeypatch):
    other = tmp_path / "other.memory"
    (other / "facts").mkdir(parents=True)
    (other / "facts" / "a.jsonl").write_text(evil_rule())
    (repo / "memory-bank").symlink_to(other)
    git(repo, "add", "memory-bank")
    git(repo, "commit", "-q", "-m", "link")
    project = find_project()
    memdir, source = resolve_memory_dir(project, None)
    assert memdir != other and source == "default"
    capsys.readouterr()
    main(["load"])
    out = capsys.readouterr().out
    assert MARKER not in out


def test_a_tracked_memory_folder_does_not_load(repo, capsys, monkeypatch):
    inside = repo / "mem"
    (inside / "facts").mkdir(parents=True)
    (inside / "facts" / "a.jsonl").write_text(evil_rule())
    git(repo, "add", "-f", "mem")
    git(repo, "commit", "-q", "-m", "mem")
    monkeypatch.setenv("MEMORY_DIR", str(inside))
    out = session_start(capsys, monkeypatch)
    assert MARKER not in out and FRAME_HEADER not in out
    assert "memory: not loaded: git in" in out and "tracks files in the memory folder" in out
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert MARKER not in out and "tracks files in the memory folder" in out
    assert main(["check"]) == 1


def test_the_owner_pointers_still_choose_the_memory(repo, tmp_path, capsys):
    elsewhere = tmp_path / "elsewhere"
    assert main(["init", "--path", str(elsewhere), "--no-default-rules"]) == 0
    project = find_project()
    assert resolve_memory_dir(project, None) == (elsewhere, ".memory-path")
    (repo / ".memory-path").unlink()
    assert resolve_memory_dir(project, None) == (elsewhere, "link")
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "git tracks" not in capsys.readouterr().out


def test_init_path_does_not_write_a_tracked_memory_path(repo, tmp_path, capsys):
    commit_on_side(repo, {".memory-path": "evil\n"})
    git(repo, "merge", "-q", "side")
    elsewhere = tmp_path / "elsewhere"
    capsys.readouterr()
    assert main(["init", "--path", str(elsewhere), "--no-default-rules"]) == 0
    assert "so the tool does not write it or read it" in capsys.readouterr().out
    assert (repo / ".memory-path").read_text() == "evil\n"
    assert resolve_memory_dir(find_project(), None) == (elsewhere, "link")


def test_outside_git_a_pointer_of_another_user_is_not_followed(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    work = shared / "work"
    work.mkdir(parents=True)
    (shared / ".memory-path").write_text("../planted\n")
    assert plain_root(work) == shared
    me = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: me + 1)
    assert plain_root(work) == work
    monkeypatch.chdir(shared)
    memdir, source = resolve_memory_dir(find_project(), None)
    assert source == "default" and memdir.name != "planted"


def test_a_memory_folder_in_a_git_repo_of_its_own_still_loads(repo, tmp_path, capsys, monkeypatch):
    """An owner may version the memory privately. Only a repo that holds the project shares it."""
    own = tmp_path / "own.memory"
    (own / "facts").mkdir(parents=True)
    (own / "facts" / "a.jsonl").write_text(evil_rule())
    git(own, "init", "-q")
    git(own, "add", "-A")
    git(own, "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "-m", "m")
    monkeypatch.setenv("MEMORY_DIR", str(own))
    out = session_start(capsys, monkeypatch)
    assert "tracks files in the memory folder" not in out and FRAME_HEADER in out


def test_a_platform_with_no_user_ids_still_loads(repo, mem, capsys, monkeypatch):
    """Windows has no os.getuid. The owner test of a pointer then has no user to compare."""
    write_facts(mem, [make_fact("f-20261001-0001", "A fact of the owner.")])
    monkeypatch.delattr(os, "getuid")
    out = session_start(capsys, monkeypatch)
    assert "Traceback" not in out and "A fact of the owner." in out
    assert main(["load"]) == 0
    assert "A fact of the owner." in capsys.readouterr().out


@pytest.mark.parametrize(
    "form",
    [[], ["--index-version", "4"], ["--split-index"], ["--index-version", "3"]],
    ids=["v2", "v4", "split", "v3"],
)
def test_a_tracked_link_is_seen_in_each_index_form(repo, tmp_path, form):
    """The index file can say "not tracked" with no git. A form that hides paths asks git."""
    other = tmp_path / "other.memory"
    (other / "facts").mkdir(parents=True)
    (repo / "memory-bank").symlink_to(other)
    git(repo, "add", "memory-bank")
    git(repo, "commit", "-q", "-m", "link")
    if form:
        git(repo, "update-index", *form)
    memdir, source = resolve_memory_dir(find_project(), None)
    assert memdir != other and source == "default"


def _commit_all(folder) -> None:
    git(folder, "add", "-A")
    git(folder, "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "-m", "m")


def test_a_memory_in_a_backup_repo_of_memories_still_loads(repo, tmp_path, capsys, monkeypatch):
    """One repo can back up the memories of several projects. It holds no project."""
    memories = tmp_path / "memories"
    for name in ("proj.memory", "other.memory"):
        (memories / name / "facts").mkdir(parents=True)
        (memories / name / "facts" / "a.jsonl").write_text(evil_rule())
    git(memories, "init", "-q")
    _commit_all(memories)
    monkeypatch.setenv("MEMORY_DIR", str(memories / "proj.memory"))
    out = session_start(capsys, monkeypatch)
    assert "tracks files in the memory folder" not in out and FRAME_HEADER in out
    assert main(["check"]) == 0
    monkeypatch.delenv("MEMORY_DIR")
    assert main(["init", "--path", str(memories / "proj.memory"), "--no-default-rules"]) == 0
    assert "proj.memory" not in (memories / ".git" / "info" / "exclude").read_text()


def test_a_repo_above_the_project_that_tracks_the_memory_refuses(
    repo, tmp_path, capsys, monkeypatch
):
    """A repo that holds the project and the memory shares the memory with the project."""
    memdir = tmp_path / "proj.memory"
    (memdir / "facts").mkdir(parents=True)
    (memdir / "facts" / "a.jsonl").write_text(evil_rule())
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-f", "proj.memory")
    git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "-m", "m")
    monkeypatch.setenv("MEMORY_DIR", str(memdir))
    out = session_start(capsys, monkeypatch)
    assert MARKER not in out and "tracks files in the memory folder" in out


def _git_that_cannot_list(tmp_path, monkeypatch) -> None:
    """A git that fails `ls-files`, as when a hook's time runs out between two git calls. Index
    version 4 makes the tool ask git."""
    folder = tmp_path / "bin"
    folder.mkdir()
    fake = folder / "git"
    real = shutil.which("git")
    fake.write_text(
        f'#!/bin/sh\nfor a in "$@"; do [ "$a" = ls-files ] && exit 1; done\nexec "{real}" "$@"\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")


def test_a_pointer_that_git_cannot_check_keeps_the_owner_memory(
    repo, tmp_path, capsys, monkeypatch
):
    """An unknown answer is no proof that git tracks the owner's pointer. A hook then must not
    set the owner's memory aside with a new empty one and a new record."""
    elsewhere = tmp_path / "elsewhere"
    assert main(["init", "--path", str(elsewhere), "--no-default-rules"]) == 0
    write_facts(elsewhere, [make_fact("f-20261001-0001", "A fact of the owner.")])
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    (repo / ".git" / "cairnkit-memory").unlink()
    git(repo, "update-index", "--index-version", "4")
    _git_that_cannot_list(tmp_path, monkeypatch)
    out = session_start(capsys, monkeypatch)
    assert "A fact of the owner." in out and "git tracks" not in out
    assert not (tmp_path / "proj.memory").exists()
    assert main(["check"]) == 0
    assert "git tracks" not in capsys.readouterr().out
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    assert "A fact of the owner." in out and "git tracks" not in out


def test_a_hook_makes_no_memory_over_a_pointer_that_git_cannot_check(
    repo, tmp_path, capsys, monkeypatch
):
    elsewhere = tmp_path / "elsewhere"
    assert main(["init", "--path", str(elsewhere), "--no-default-rules"]) == 0
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    shutil.rmtree(elsewhere)
    (repo / "memory-bank").unlink()
    (repo / ".git" / "cairnkit-memory").unlink()
    git(repo, "update-index", "--index-version", "4")
    _git_that_cannot_list(tmp_path, monkeypatch)
    session_start(capsys, monkeypatch)
    assert not elsewhere.exists() and not (tmp_path / "proj.memory").exists()
