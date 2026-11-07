"""A pipe or a device where a project or memory file belongs hangs no command."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_FILES = [
    ".cursor/hooks.json",
    ".codex/hooks.json",
    ".claude/settings.local.json",
    "CLAUDE.md",
    "AGENTS.md",
    "CLAUDE.local.md",
    ".env",
    ".memory-path",
    ".github/workflows/ci.yml",
    ".pre-commit-config.yaml",
]
MEMORY_FILES = ["notes/status.md", "notes/extra.md", "facts/odd.jsonl", "config.toml"]
COMMANDS = [("status",), ("check",), ("load",), ("hooks", "install")]


def run_cli(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    """The CLI in its own process, so that a hang fails the test and does not stop the run."""
    argv = [sys.executable, "-m", "cairnkit", *args]
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=10)


def pipe(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    os.mkfifo(path)


@pytest.mark.parametrize("args", COMMANDS, ids=" ".join)
@pytest.mark.parametrize("rel", PROJECT_FILES)
def test_a_pipe_in_the_project_hangs_no_command(mem: Path, repo: Path, rel: str, args):
    pipe(repo / rel)
    done = run_cli(repo, *args)
    assert "Traceback" not in done.stderr, done.stderr


@pytest.mark.parametrize("args", COMMANDS, ids=" ".join)
@pytest.mark.parametrize("rel", MEMORY_FILES)
def test_a_pipe_in_the_memory_folder_hangs_no_command(mem: Path, repo: Path, rel: str, args):
    pipe(mem / rel)
    done = run_cli(repo, *args)
    assert "Traceback" not in done.stderr, done.stderr


def test_the_reader_refuses_a_pipe_a_device_a_folder_and_a_big_file(tmp_path: Path):
    from cairnkit import plainfile

    pipe(tmp_path / "pipe")
    big = tmp_path / "big"
    big.write_bytes(b"x" * 11)
    for path in (tmp_path / "pipe", Path(os.devnull), tmp_path):
        with pytest.raises(OSError):
            plainfile.read_bytes(path)
    with pytest.raises(OSError):
        plainfile.read_bytes(big, limit=10)
    assert plainfile.read_bytes(big, limit=11) == b"x" * 11


@pytest.mark.parametrize(
    ("data", "encoding", "errors"),
    [
        (b"a\r\nb\rc\n", "utf-8", None),
        (b"\xef\xbb\xbfhead\xff\n", "utf-8-sig", "replace"),
        (b"plain\n", None, None),
    ],
)
def test_the_reader_gives_what_read_text_gives(tmp_path: Path, data: bytes, encoding, errors):
    from cairnkit import plainfile

    path = tmp_path / "f"
    path.write_bytes(data)
    want = path.read_text(encoding=encoding, errors=errors)
    assert plainfile.read_text(path, encoding=encoding, errors=errors) == want
    with plainfile.open_text(path, encoding=encoding, errors=errors) as fh:
        assert fh.read() == want


def test_a_link_is_refused_only_when_asked(tmp_path: Path):
    from cairnkit import plainfile

    (tmp_path / "real").write_text("text\n")
    (tmp_path / "link").symlink_to(tmp_path / "real")
    assert plainfile.read_text(tmp_path / "link") == "text\n"
    with pytest.raises(OSError):
        plainfile.read_text(tmp_path / "link", follow=False)


# Reads of files that ship with the tool or that it installed itself, never a project file.
OWN_FILES = {"install_source.py", "update.py", "plainfile.py"}
OWN_SITES = {("presets.py", "tomllib.loads(path.read_text(")}
# Not a raw read: the reader itself, an open of no file, and the memory's own `open`.
OPENERS = {"plainfile", "os", "tarfile", "Memory", "io"}


def _raw_reads(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    found = []
    for node in ast.walk(ast.parse(text)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr, line = node.func.attr, lines[node.lineno - 1]
        owner = node.func.value.id if isinstance(node.func.value, ast.Name) else None
        mode = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) else "r"
        reads = owner not in OPENERS and (
            attr in ("read_text", "read_bytes") or (attr == "open" and "r" in str(mode))
        )
        if reads and not any(path.name == f and s in line for f, s in OWN_SITES):
            found.append(f"{path.name}:{node.lineno}: {line.strip()}")
    return found


def test_each_read_of_a_project_or_memory_file_goes_through_the_plain_reader():
    """A new `Path.read_text` would bring the hang of a pipe back. Use `plainfile`."""
    import cairnkit

    src = Path(cairnkit.__file__).parent
    found = [
        line
        for path in sorted(src.glob("*.py"))
        if path.name not in OWN_FILES
        for line in _raw_reads(path)
    ]
    assert found == []


def test_a_fact_file_over_64_mb_still_loads_and_purges(mem: Path, repo: Path, capsys):
    """Only a pipe or a device is refused; a big regular fact file is read in full."""
    from conftest import make_fact, write_facts

    from cairnkit import store
    from cairnkit.cli import main

    big = make_fact("f-big", "y" * (65 * 1024 * 1024))
    small = make_fact("f-small", "We chose SQLite over Postgres.")
    gone = make_fact("f-gone", "This fact goes.")
    write_facts(mem, [big, small, gone])
    found, bad = store.scan(store.fact_files(mem))
    assert {item.record["id"] for item in found} == {"f-big", "f-small", "f-gone"}
    assert bad == []
    assert store.drop_id(mem, "f-gone") == 1
    capsys.readouterr()
    main(["load"])
    assert "We chose SQLite over Postgres." in capsys.readouterr().out
