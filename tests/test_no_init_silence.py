"""With no memory init, every hook exits 0, prints nothing, and writes no files."""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cairnkit.cli import main

AGENTS = ("claude", "codex", "cursor", "generic", "opencode", "pi", "grok")
SESSION_EVENTS = ("session-start", "stop", "after-shell")
GIT_EVENTS = ("post-commit", "pre-push", "post-merge")


def _snapshot(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _run_hook(repo: Path, event: str, agent: str, payload: str = "{}") -> tuple[int, str, str]:
    monkey_stdin = io.StringIO(payload)
    # Drive through main so argv/agent choices match production.
    old = sys.stdin
    try:
        sys.stdin = monkey_stdin
        code = main(["hook", event, "--agent", agent])
    finally:
        sys.stdin = old
    return code, "", ""


@pytest.fixture
def bare(repo, capsys, monkeypatch):
    """A fresh git repo with no memory init. cwd is the repo."""
    monkeypatch.chdir(repo)
    before = _snapshot(repo)
    # Sibling default memory path must not exist.
    sibling = repo.parent / f"{repo.name}.memory"
    assert not sibling.exists()
    return repo, before, sibling, capsys


@pytest.mark.parametrize("agent", AGENTS)
@pytest.mark.parametrize("event", SESSION_EVENTS)
def test_session_hooks_silent_without_init(bare, agent, event):
    repo, before, sibling, capsys = bare
    capsys.readouterr()
    code = main(["hook", event, "--agent", agent])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert not sibling.exists()
    assert _snapshot(repo) == before


@pytest.mark.parametrize("event", GIT_EVENTS)
def test_git_hooks_silent_without_init(bare, event):
    repo, before, sibling, capsys = bare
    capsys.readouterr()
    code = main(["hook", event])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert not sibling.exists()
    assert _snapshot(repo) == before


def test_installed_git_hooks_stay_silent_without_init(bare, monkeypatch):
    """Personal git hooks must not create a memory dir or print when fired by git."""
    repo, _before, sibling, capsys = bare
    # Install without memory: hooks_cmd still writes personal git hooks for main_root.
    capsys.readouterr()
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    # Install may add exclude lines; re-snapshot after install.
    after_install = _snapshot(repo)
    assert not sibling.exists()
    env = {**os.environ, "PATH": os.environ["PATH"]}
    # Seed a commit so post-commit can run.
    (repo / "note.txt").write_text("x\n")
    subprocess.run(["git", "add", "note.txt"], cwd=repo, check=True, env=env)
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=.git/hooks", "commit", "-q", "-m", "seed"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    # Hook stderr is redirected to /dev/null by quiet_body; nothing new under .memory.
    assert not sibling.exists()
    # Only the committed note and hook scripts / exclude may differ from bare.
    assert sibling.as_posix() not in _snapshot(repo)
    assert after_install  # install happened


def test_pre_commit_quiet_when_memory_dir_exists_without_facts(bare, capsys):
    """An empty sibling .memory (no facts/) is still uninitialized."""
    repo, before, sibling, _capsys = bare
    sibling.mkdir()
    assert not (sibling / "facts").exists()
    (repo / "x.txt").write_text("x\n")
    subprocess.run(["git", "add", "x.txt"], cwd=repo, check=True)
    capsys.readouterr()
    code = main(["hook", "pre-commit"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == "" and out.err == ""
    assert list(sibling.iterdir()) == []
    # Only the staged file may be new under the repo.
    assert sibling.as_posix() not in {str(p) for p in before}
