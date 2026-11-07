"""A pipe or a device where a project or memory file belongs hangs no command."""

from __future__ import annotations

import ast
import json
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


def test_the_writer_refuses_a_pipe_a_device_and_a_folder_without_a_wait(tmp_path: Path):
    from cairnkit import plainfile

    pipe(tmp_path / "pipe")
    for path in (tmp_path / "pipe", Path(os.devnull), tmp_path):
        for write in (
            lambda p: plainfile.write_text(p, "x"),
            lambda p: plainfile.write_bytes(p, b"x"),
            lambda p: plainfile.open_write(p, "a").close(),
            lambda p: plainfile.open_write(p, "ab").close(),
        ):
            with pytest.raises(OSError):
                write(path)
    assert (tmp_path / "pipe").is_fifo()


def test_the_writer_gives_what_path_gives(tmp_path: Path):
    from cairnkit import plainfile

    path, want = tmp_path / "f", tmp_path / "want"
    for target, write in ((path, plainfile.write_text), (want, Path.write_text)):
        target.write_text("old text that is long\n")
        write(target, "newü\n", encoding="utf-8")
        with plainfile.open_write(target, "a", encoding="utf-8") as fh:
            fh.write("more\n")
    assert path.read_bytes() == want.read_bytes() == "newü\nmore\n".encode()
    plainfile.write_bytes(path, b"\x00bytes")
    assert path.read_bytes() == b"\x00bytes"
    with pytest.raises(FileExistsError):
        plainfile.open_write(path, "w", new=True)
    (tmp_path / "link").symlink_to(path)
    with pytest.raises(OSError):
        plainfile.open_write(tmp_path / "link", "w", follow=False)
    assert path.read_bytes() == b"\x00bytes"
    plainfile.open_write(tmp_path / "new", "w", new=True, perms=0o600).close()
    assert (tmp_path / "new").stat().st_mode & 0o777 == 0o600


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


OWN_WRITE_SITES = {("cli.py", "os.open(os.devnull")}


def _mode(node: ast.Call, at: int) -> str:
    """The mode argument of an open call, or "r"."""
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return str(kw.value.value)
    arg = node.args[at] if len(node.args) > at else None
    return str(arg.value) if isinstance(arg, ast.Constant) else "r"


def _raw_writes(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    found = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        func, call = node.func, ast.get_source_segment(text, node) or ""
        if isinstance(func, ast.Name):
            writes = func.id == "open" and any(c in _mode(node, 1) for c in "wax+")
        elif isinstance(func, ast.Attribute):
            owner = func.value.id if isinstance(func.value, ast.Name) else None
            if owner == "plainfile":
                continue
            if owner == "os":
                writes = func.attr == "open" and "O_RDONLY" not in call
            else:
                writes = func.attr in ("write_text", "write_bytes") or (
                    func.attr == "open"
                    and owner not in OPENERS
                    and any(c in _mode(node, 0) for c in "wax+")
                )
        else:
            continue
        line = lines[node.lineno - 1]
        if writes and not any(path.name == f and s in line for f, s in OWN_WRITE_SITES):
            found.append(f"{path.name}:{node.lineno}: {line.strip()}")
    return found


def test_each_write_of_a_project_or_memory_file_goes_through_the_plain_writer():
    """A new `Path.write_text` or `open(..., "a")` would bring the hang of a pipe back."""
    import cairnkit

    src = Path(cairnkit.__file__).parent
    found = [
        line
        for path in sorted(src.glob("*.py"))
        if path.name not in OWN_FILES
        for line in _raw_writes(path)
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


SESSION = {"session_id": "s1", "cwd": "."}
SWEEP = {
    "load": (("load",), None),
    "check": (("check",), None),
    "status": (("status",), None),
    "add": (("add", "We chose SQLite over Postgres for the cache."), None),
    "search": (("search", "SQLite"), None),
    "tidy": (("tidy",), None),
    "export": (("export",), None),
    "repair": (("repair",), None),
    "init --refresh": (("init", "--refresh"), None),
    "hooks install": (("hooks", "install", "--agent", "claude"), None),
    "instructions": (("instructions", "--write-instructions", "local"), None),
    "hook session-start": (
        ("hook", "session-start", "--agent", "claude"),
        {**SESSION, "source": "startup"},
    ),
    "hook prompt": (("hook", "prompt", "--agent", "claude"), {**SESSION, "prompt": "Use uv."}),
    "hook before-shell": (
        ("hook", "before-shell", "--agent", "claude"),
        {**SESSION, "tool_name": "Bash", "tool_input": {"command": "pip install requests"}},
    ),
    "hook pre-compact": (("hook", "pre-compact", "--agent", "claude"), SESSION),
    "hook pre-commit": (("hook", "pre-commit"), None),
    "hook stop": (("hook", "stop", "--agent", "claude"), SESSION),
}
# Files that hung a command before each write opened without a wait. The sweep must reach them.
REACHED = {
    "hook session-start": ["memory/.auto-tidy-state.json", "memory/.auto-tidy.lock"],
    "hooks install": ["memory/.agents-seen.json", "memory/tool-version.json"],
    "init --refresh": ["memory/tool-version.json"],
    "add": ["memory/facts/main.jsonl", "memory/facts/.write.lock"],
}


@pytest.mark.parametrize("name", SWEEP)
def test_a_pipe_at_any_file_that_a_command_opens_hangs_nothing(
    mem: Path, repo: Path, tmp_path: Path, name: str
):
    """Each file in the project or the memory folder that the command opens, read or write, is
    a pipe in turn. The sweep finds the files itself, so a new file is in it."""
    from cairnkit.cli import main

    assert main(["hooks", "install", "--agent", "claude"]) == 0
    assert main(["add", "We chose uv over pip for installs."]) == 0
    args, payload = SWEEP[name]
    work = tmp_path / "sweep"
    work.mkdir()
    plan = {
        "root": str(repo),
        "memdir": str(mem),
        "args": list(args),
        "stdin": json.dumps(payload) if payload else "",
        "timeout": 10,
    }
    (work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    driver = Path(__file__).with_name("odd_file_sweep.py")
    subprocess.run(
        [sys.executable, str(driver), str(work / "plan.json"), str(work / "result.json")],
        check=True,
        timeout=900,
    )
    result = json.loads((work / "result.json").read_text(encoding="utf-8"))
    names = {
        "memory/" + Path(p).relative_to(mem.resolve()).as_posix()
        for p in result["opened"]
        if Path(p).is_relative_to(mem.resolve())
    }
    assert set(REACHED.get(name, [])) <= names
    assert result["problems"] == {}
