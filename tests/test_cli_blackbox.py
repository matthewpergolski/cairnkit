"""Black-box test: run the installed `cairnkit` and `memory` scripts in a temp repo.

It uses no import of the package. It checks only exit codes, files and output, so
another implementation can run the same steps. A dead proxy keeps it off the
network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from cairnkit import __version__  # only to know the expected version

BIN = Path(sys.executable).parent


@pytest.fixture
def run(repo, tmp_path):
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "http_proxy": "http://127.0.0.1:9",
        "https_proxy": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "",
        "no_proxy": "",
    }
    (tmp_path / "home").mkdir()

    def call(*args: str, command: str = "cairnkit", cwd: Path = repo):
        script = BIN / command
        assert script.is_file(), f"{script} is not installed; run uv sync"
        done = subprocess.run(
            [str(script), *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )
        return done.returncode, done.stdout, done.stderr

    return call


def test_both_scripts_report_their_name_and_version(run):
    assert run("--version") == (0, f"cairnkit {__version__}\n", "")
    assert run("--version", command="memory") == (0, f"memory {__version__}\n", "")


def test_init_status_check_add_search(repo, run):
    code, out, _ = run("check")
    assert code == 0
    assert "skipped: no memory folder" in out

    code, out, _ = run("init")
    assert code == 0
    link = repo / "memory-bank"
    assert link.is_symlink()
    assert os.readlink(link) == "../proj.memory"
    assert (repo.parent / "proj.memory" / "facts").is_dir()
    exclude = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert "memory-bank" in exclude and ".memory-path" in exclude

    code, out, _ = run("status")
    assert code == 0
    assert __version__ in out
    assert "Repo files: current." in out

    code, out, _ = run("check")
    assert code == 0
    assert out.startswith("memory check: ok")

    text = "The test suite needs Docker running."
    code, out, _ = run(
        "add", text, "--kind", "trap", "--area", "tests", "--basis", "seen",
        "--source", "session:2026-10-25", command="memory",
    )  # fmt: skip
    assert code == 0
    assert out.startswith("added f-")
    fact_id = out.split()[1]

    code, out, _ = run("search", "docker")
    assert code == 0
    assert f"[{fact_id}] {text}" in out
    assert "--- end of stored notes ---" in out

    code, out, _ = run("search", "nothing-matches-this")
    assert code == 0
    assert fact_id not in out

    code, out, _ = run("check", "--strict")
    assert code == 0


def test_bad_arguments_exit_2(run):
    code, _, err = run("search")
    assert code == 2
    assert "usage: cairnkit search" in err
