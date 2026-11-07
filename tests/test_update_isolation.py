"""`memory update` builds and installs the same way from any folder.

uv reads `uv.toml`, `pyproject.toml` and a `.venv` from the folder that it starts in. A repo
holds such files, and an update that ran there would build the tool that every hook runs with
the repo's index, or run the repo's `.venv/bin/python`.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
from pathlib import Path

import pytest

from cairnkit import update
from cairnkit.progress import Progress

UNREACHABLE = '[[index]]\nurl = "http://127.0.0.1:9/simple"\ndefault = true\n'


def tiny_source(path: Path) -> Path:
    (path / "cairnkit").mkdir(parents=True)
    (path / "cairnkit" / "__init__.py").write_text("def main():\n    return 0\n")
    (path / "pyproject.toml").write_text(
        '[project]\nname = "cairnkit"\nversion = "0.0.1"\n'
        '[project.scripts]\nmemory = "cairnkit:main"\n'
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
    )
    return path


def repo_folder(path: Path, marker: Path) -> Path:
    """A folder with uv settings and a `.venv` of its own, as a cloned repo can have."""
    (path / ".venv" / "bin").mkdir(parents=True)
    shim = path / ".venv" / "bin" / "python"
    shim.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    shim.chmod(0o755)
    (path / ".venv" / "pyvenv.cfg").write_text("home = /usr/bin\n")
    (path / "uv.toml").write_text(UNREACHABLE)
    (path / "pyproject.toml").write_text(f'[project]\nname = "repo"\n[tool.uv]\n{UNREACHABLE}')
    return path


@pytest.fixture
def real_uv(tmp_path, monkeypatch) -> str:
    """The real uv, offline, with its own tool folders. Skips when it cannot build offline."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_PYTHON", sys.executable)
    monkeypatch.setenv("UV_TOOL_DIR", str(tmp_path / "tools"))
    monkeypatch.setenv("UV_TOOL_BIN_DIR", str(tmp_path / "tool-bin"))
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.chdir(control)
    try:
        update._build(Progress(io.StringIO()), uv, tiny_source(tmp_path / "probe"), control)
    except update.SourceError:
        pytest.skip("hatchling is not in the uv cache, and tests use no network")
    return uv


def test_a_build_from_a_repo_folder_uses_no_setting_of_that_folder(real_uv, tmp_path, monkeypatch):
    marker = tmp_path / "MARKER"
    monkeypatch.chdir(repo_folder(tmp_path / "repo", marker))
    work = tmp_path / "work"
    work.mkdir()
    wheel = update._build(Progress(io.StringIO()), real_uv, tiny_source(tmp_path / "src"), work)
    assert wheel.is_file()
    assert not marker.exists()


def test_an_install_from_a_repo_folder_still_installs(real_uv, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    wheel = update._build(Progress(io.StringIO()), real_uv, tiny_source(tmp_path / "src"), work)
    marker = tmp_path / "MARKER"
    monkeypatch.chdir(repo_folder(tmp_path / "repo", marker))
    monkeypatch.setattr(update, "wheels_dir", lambda: tmp_path / "kept")
    update._install(Progress(io.StringIO()), real_uv, None, wheel, None)
    assert (tmp_path / "tool-bin" / "memory").exists()
    assert not marker.exists()


def test_the_owner_uv_settings_still_count(tmp_path, monkeypatch):
    config = tmp_path / "config"
    (config / "uv").mkdir(parents=True)
    (config / "uv" / "uv.toml").write_text('python-preference = "only-managed"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.delenv("UV_CONFIG_FILE", raising=False)
    log = tmp_path / "uv.log"
    fake = tmp_path / "uv"
    fake.write_text(f'#!/bin/sh\necho "$PWD $*" >> {log}\nexit 1\n')
    fake.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(update.SourceError):
        update._build(Progress(io.StringIO()), str(fake), tmp_path / "src", tmp_path)
    line = log.read_text()
    assert "--no-config" in line and f"--config-file {config / 'uv' / 'uv.toml'}" in line
    assert not line.startswith(f"{os.path.realpath(tmp_path)} ")
