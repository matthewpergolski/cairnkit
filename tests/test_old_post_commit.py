"""A session start removes the 0.3.1 post-commit block by itself, and only that text."""

from __future__ import annotations

import io
import os
import stat

import pytest
from conftest import git

from cairnkit import githook
from cairnkit.cli import main

BLOCK = (
    "# >>> cairnkit >>>\n'/old/python' -m cairnkit hook post-commit || true\n# <<< cairnkit <<<\n"
)


def session_start(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "s"}'))
    assert main(["hook", "session-start", "--agent", "claude"]) == 0


@pytest.fixture
def hook(repo, mem):
    return repo / ".git" / "hooks" / "post-commit"


def test_the_block_alone_goes_with_its_file(hook, monkeypatch):
    hook.write_text(f"#!/bin/sh\n{BLOCK}")
    session_start(monkeypatch)
    assert not hook.exists()


@pytest.mark.parametrize(
    "marks",
    [("# >>> cairnkit >>>", "# <<< cairnkit <<<"), githook.PAIRS[1]],
    ids=["current", "before-the-rename"],
)
def test_foreign_text_stays_byte_for_byte(hook, monkeypatch, marks):
    head = b"#!/bin/sh\r\necho foreign \xff\xfe bytes\r\n"
    tail = b"# after\t  \r\nexit 0\n"
    block = f"{marks[0]}\nold line\n{marks[1]}\n".encode()
    hook.write_bytes(head + block + tail)
    hook.chmod(0o754)
    session_start(monkeypatch)
    assert hook.read_bytes() == head + tail
    assert stat.S_IMODE(os.stat(hook).st_mode) == 0o754


def test_a_foreign_hook_with_no_block_does_not_change(hook, monkeypatch):
    foreign = b"#!/bin/sh\r\necho only foreign \xff\n"
    hook.write_bytes(foreign)
    session_start(monkeypatch)
    assert hook.read_bytes() == foreign


@pytest.mark.parametrize(
    "text",
    [
        b"#!/bin/sh\n# >>> cairnkit >>>\nmine\n",
        b"#!/bin/sh\nmine\n# <<< cairnkit <<<\n",
        b"#!/bin/sh\n" + BLOCK.encode() + BLOCK.encode(),
    ],
    ids=["no-end", "no-start", "two-blocks"],
)
def test_a_lost_marker_does_not_change(hook, monkeypatch, text):
    hook.write_bytes(text)
    session_start(monkeypatch)
    assert hook.read_bytes() == text


def test_a_tracked_hooks_folder_does_not_change(repo, mem, monkeypatch):
    folder = repo / "tracked"
    folder.mkdir()
    git(repo, "config", "core.hooksPath", "tracked")
    path = folder / "post-commit"
    path.write_text(f"#!/bin/sh\n{BLOCK}")
    session_start(monkeypatch)
    assert path.read_text() == f"#!/bin/sh\n{BLOCK}"


def test_a_hooks_folder_linked_out_of_git_does_not_change(repo, mem, monkeypatch, tmp_path):
    folder = tmp_path / "linked-hooks"
    folder.mkdir()
    path = folder / "post-commit"
    path.write_text(f"#!/bin/sh\n{BLOCK}")
    hooks = repo / ".git" / "hooks"
    if hooks.exists():
        for item in hooks.iterdir():
            item.unlink()
        hooks.rmdir()
    hooks.symlink_to(folder)
    session_start(monkeypatch)
    assert path.read_text() == f"#!/bin/sh\n{BLOCK}"


def test_the_block_goes_with_no_memory_here(repo, monkeypatch, tmp_path):
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text(f"#!/bin/sh\n{BLOCK}")
    session_start(monkeypatch)
    assert not hook.exists()


def test_a_session_start_ends_the_repeat_line_about_the_block(hook, monkeypatch, capsys):
    hook.write_text(f"#!/bin/sh\n{BLOCK}")
    capsys.readouterr()
    session_start(monkeypatch)
    out = capsys.readouterr().out
    assert "post-commit" not in out
    assert main(["check", "--strict"]) == 0


def test_a_broken_hook_does_not_stop_the_session(hook, monkeypatch, capsys):
    hook.mkdir()
    session_start(monkeypatch)
    assert hook.is_dir()
