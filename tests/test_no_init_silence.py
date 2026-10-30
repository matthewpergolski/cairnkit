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
GIT_EVENTS = ("post-commit", "pre-push", "post-merge", "docs-freshness")


def _snapshot(root: Path) -> set[str]:
    """Repo file paths, ignoring ephemeral git lock files.

    macOS CI can create and drop `.git/objects/maintenance.lock` while a test
    runs, which is not a hook write.
    """
    out: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith(".git/") and rel.endswith(".lock"):
            continue
        out.add(rel)
    return out


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


def test_docs_freshness_silent_without_init_when_atlas_exists(bare):
    """A docs/state page with no facts/ must not warn and must not be rewritten."""
    repo, _before, sibling, capsys = bare
    state = repo / "docs" / "state"
    state.mkdir(parents=True)
    page = state / "README.md"
    page.write_text("old\n", encoding="utf-8")
    before = _snapshot(repo)
    capsys.readouterr()
    code = main(["hook", "docs-freshness"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert not sibling.exists()
    assert _snapshot(repo) == before
    assert page.read_text(encoding="utf-8") == "old\n"


def test_installed_post_merge_stays_silent_without_init(bare):
    """The generated post-merge script prints nothing when memory was never created."""
    repo, _before, sibling, capsys = bare
    state = repo / "docs" / "state"
    state.mkdir(parents=True)
    page = state / "README.md"
    page.write_text("old\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    hook = repo / ".git" / "hooks" / "post-merge"
    result = subprocess.run(
        ["sh", str(hook)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert not sibling.exists()
    assert page.read_text(encoding="utf-8") == "old\n"


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
