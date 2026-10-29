"""Shared test helpers: throwaway git repos and worktrees."""

from __future__ import annotations

import shlex
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout


def hung_marker() -> str:
    """Opaque token unique to one test run; safe to embed in process argv."""
    return f"cairnkit-hung-{uuid.uuid4().hex}"


def write_hung_interpreter(path: Path, marker: str, seconds: float = 60) -> None:
    """Write a fake python that hangs; *marker* stays visible in ``ps`` args.

    Uses an absolute interpreter and ``python -c`` so a restricted PATH still
    works, and so ``exec`` keeps the marker in argv (unlike ``exec /bin/sleep``).
    """
    code = f"import time; time.sleep({seconds})  # {marker}"
    path.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} -c {shlex.quote(code)}\n")
    path.chmod(0o755)


def processes_with_marker(marker: str) -> list[str]:
    """Running processes whose args contain *marker* (``pid ppid args`` lines)."""
    out = subprocess.check_output(["ps", "-eo", "pid=,ppid=,args="], text=True)
    found: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) == 3 and marker in parts[2]:
            found.append(line)
    return found


def assert_marker_gone(marker: str, *, label: str = "hung process") -> None:
    """Fail if any process still carries *marker* in its argv."""
    leftover = processes_with_marker(marker)
    assert not leftover, f"leftover {label}: {leftover}"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Tests must not see the caller's memory settings."""
    for name in (
        "MEMORY_DIR",
        "MEMORY_WRITER",
        "MEMORY_NOW",
        "CLAUDECODE",
        "CODEX_CI",
        "CODEX_SANDBOX",
        "CODEX_THREAD_ID",
        "CURSOR_AGENT",
        "CURSOR_TRACE_ID",
        "OPENCODE",
        "OPENCODE_SESSION_ID",
        "PI_CODING_AGENT",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture(autouse=True)
def no_real_machine(tmp_path_factory, monkeypatch):
    """An empty home, no network and no real install, so the skills check says nothing.

    Also pins XDG_CONFIG_HOME (and cache) under the fake machine. GitHub ubuntu
    runners often set XDG_CONFIG_HOME to the real ~/.config; without this pin,
    OpenCode detection escapes HOME and tests share / pollute the runner.
    """
    from cairnkit import skills

    machine = tmp_path_factory.mktemp("machine")  # outside the test's own tmp folder
    (machine / "home").mkdir()
    monkeypatch.setenv("HOME", str(machine / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(machine / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(machine / "config"))

    def offline(*args, **kwargs):
        raise OSError("tests do not use the network")

    monkeypatch.setattr(skills, "fetch_text", offline)
    monkeypatch.setattr(skills, "_which", lambda name: None)
    monkeypatch.setattr(skills, "_run", lambda argv, timeout=120: (1, "tests run no commands"))
    monkeypatch.setattr(skills, "checkout", offline)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A git repo at <tmp>/proj with one commit, on branch main. CWD is the repo."""
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("test\n")
    (root / ".gitignore").write_text(".worktrees/\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    monkeypatch.chdir(root)
    return root


def add_worktree(repo: Path, branch: str) -> Path:
    path = repo / ".worktrees" / branch
    git(repo, "worktree", "add", "-q", "-b", branch, str(path))
    return path


def read_jsonl(path: Path) -> list[dict]:
    import json

    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
def mem(repo: Path) -> Path:
    """A repo with memory set up, with no default rules. Returns the memory folder."""
    from cairnkit.cli import main

    assert main(["init", "--no-default-rules"]) == 0
    return repo.parent / "proj.memory"


FIXTURES = Path(__file__).parent / "fixtures"

# Every rule key of the dev preset. A new or renamed rule must change this set.
DEV_KEYS = {
    "commits.co-author",
    "commits.generated",
    "commits.author",
    "basic.files",
    "basic.commands",
    "basic.privacy",
    "basic.secrets",
    "basic.assumptions",
    "basic.search-first",
    "dev.verify",
    "dev.tests",
    "dev.scope",
    "dev.ask",
    "dev.git",
    "dev.commit-secrets",
    "dev.generated",
    "dev.lockfile",
}


def make_fact(fid: str, text: str, **extra) -> dict:
    base = {
        "type": "fact",
        "id": fid,
        "kind": "fact",
        "text": text,
        "area": "general",
        "happened_at": "2026-10-01",
        "learned_at": "2026-10-01T12:00:00+00:00",
        "source": "session:2026-10-01",
        "basis": "seen",
        "status": "active",
        "scope": "long",
        "writer": "main",
    }
    base.update(extra)
    return base


def write_facts(mem: Path, records: list[dict], name: str = "main.jsonl") -> None:
    import json

    path = mem / "facts" / name
    with path.open("a") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
