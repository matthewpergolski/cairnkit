"""The package version has one source: src/cairnkit/__init__.py."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from cairnkit import __version__, install_source

ROOT = Path(__file__).resolve().parents[1]
FORMAT = ROOT / "docs" / "FORMAT.md"


def test_format_doc_version_matches_module():
    text = FORMAT.read_text(encoding="utf-8")
    match = re.search(r"It describes version ([0-9][0-9a-zA-Z.+-]*)\.", text)
    assert match is not None, "docs/FORMAT.md must state the format version"
    assert match.group(1) == __version__


def test_pyproject_version_is_dynamic_from_init():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in data["project"]
    assert "version" in data["project"].get("dynamic", [])
    assert data["tool"]["hatch"]["version"]["path"] == "src/cairnkit/__init__.py"


def test_folder_version_reads_dynamic_init(tmp_path):
    """A source folder with hatch dynamic version still reports the module version."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "cairnkit"\ndynamic = ["version"]\n'
        '[tool.hatch.version]\npath = "src/cairnkit/__init__.py"\n',
        encoding="utf-8",
    )
    init = tmp_path / "src" / "cairnkit" / "__init__.py"
    init.parent.mkdir(parents=True)
    init.write_text('__version__ = "9.8.7"\n', encoding="utf-8")
    assert install_source.folder_version(tmp_path) == "9.8.7"
