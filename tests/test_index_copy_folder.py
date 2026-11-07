"""The folder for index copies is used only when it is a private folder of this user."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest
from conftest import git

from cairnkit import paths


@pytest.fixture
def temp_root(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    monkeypatch.setattr(paths, "_INDEX_COPIES", {})
    monkeypatch.setattr(paths, "_INDEX_PATHS", {})
    return root


def folder_in(root: Path) -> Path:
    return root / f"cairnkit-index-{os.getuid()}"


def old_file(folder: Path) -> Path:
    path = folder / "index-old"
    path.write_text("keep\n")
    past = time.time() - 7200
    os.utime(path, (past, past))
    return path


def staged_diff(repo: Path) -> str | None:
    (repo / "new.txt").write_text("x\n")
    git(repo, "add", "new.txt")
    return paths.run_git(repo, "diff", "--cached", "--name-only")


def test_a_private_folder_gets_the_copy_and_loses_old_copies(repo, temp_root):
    folder = folder_in(temp_root)
    folder.mkdir(mode=0o700)
    old = old_file(folder)
    assert staged_diff(repo) == "new.txt"
    assert not old.exists()
    assert [p.name for p in folder.iterdir() if p.name.startswith("index-")]


def test_a_link_at_the_folder_name_is_not_used_or_cleaned(repo, temp_root, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    old = old_file(elsewhere)
    folder_in(temp_root).symlink_to(elsewhere)
    assert staged_diff(repo) == "new.txt"
    assert old.read_text() == "keep\n"
    assert [p.name for p in elsewhere.iterdir()] == ["index-old"]


def test_a_folder_that_others_can_write_is_not_used_or_cleaned(repo, temp_root):
    folder = folder_in(temp_root)
    folder.mkdir()
    folder.chmod(0o777)
    old = old_file(folder)
    assert staged_diff(repo) == "new.txt"
    assert [p.name for p in folder.iterdir()] == [old.name]


def test_a_folder_of_another_user_is_not_used_or_cleaned(repo, temp_root, monkeypatch):
    folder = folder_in(temp_root)
    folder.mkdir(mode=0o700)
    old = old_file(folder)
    real_lstat = os.lstat

    def other_owner(path, *args, **kwargs):
        found = real_lstat(path, *args, **kwargs)
        if Path(path) != folder:
            return found
        fields = list(found[:10])
        fields[4] = found.st_uid + 1
        return os.stat_result(fields)

    monkeypatch.setattr(os, "lstat", other_owner)
    assert staged_diff(repo) == "new.txt"
    assert [p.name for p in folder.iterdir()] == [old.name]


def test_a_link_inside_the_folder_is_not_followed_by_the_clean(repo, temp_root, tmp_path):
    folder = folder_in(temp_root)
    folder.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.mkdir()
    kept = old_file(target)
    (folder / "index-link").symlink_to(target)
    (folder / "index-file-link").symlink_to(kept)
    past = time.time() - 7200
    for name in ("index-link", "index-file-link"):
        os.utime(folder / name, (past, past), follow_symlinks=False)
    assert staged_diff(repo) == "new.txt"
    assert kept.read_text() == "keep\n"
