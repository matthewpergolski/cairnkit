"""A load never moves ownership. With its owner gone, a move and a copy can each claim a memory."""

from __future__ import annotations

import itertools
import re
import shutil

import pytest
from conftest import git

from cairnkit.cli import main
from cairnkit.paths import read_identity

FACT = "Trap: billing webhook retries forever"
ADD = ["add", FACT, "--kind", "trap", "--pinned", "--basis", "seen", "--source", "s:1"]


def run(capsys, *args):
    capsys.readouterr()
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


@pytest.fixture
def first(repo, mem, capsys):
    assert main(ADD) == 0
    assert main(["load"]) == 0
    capsys.readouterr()
    return repo


def copy_of(repo, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(repo, copy, symlinks=True)
    return copy


def moved_from(repo, tmp_path):
    new = tmp_path / "moved"
    repo.rename(new)
    return new


def owner(mem):
    return read_identity(mem).owner


def key(repo):
    return (repo / ".git").resolve()


def test_a_load_in_a_copy_does_not_take_a_memory_whose_owner_moved(
    first, mem, capsys, tmp_path, monkeypatch
):
    before = owner(mem)
    copy = copy_of(first, tmp_path)
    moved = moved_from(first, tmp_path)
    monkeypatch.chdir(copy)
    _, out = run(capsys, "load")
    assert FACT in out
    assert owner(mem) == before
    assert str(mem) in out and str(moved) in out


def test_the_real_repo_is_not_told_it_is_a_copy(first, mem, capsys, tmp_path, monkeypatch):
    copy = copy_of(first, tmp_path)
    moved = moved_from(first, tmp_path)
    monkeypatch.chdir(copy)
    run(capsys, "load")
    monkeypatch.chdir(moved)
    _, out = run(capsys, "load")
    assert FACT in out
    assert "is a copy" not in out
    assert str(mem) in out and str(copy) in out


def test_neither_line_prints_a_fix_that_gives_an_empty_memory(
    first, mem, capsys, tmp_path, monkeypatch
):
    copy = copy_of(first, tmp_path)
    moved = moved_from(first, tmp_path)
    for folder in (copy, moved):
        monkeypatch.chdir(folder)
        _, out = run(capsys, "load")
        line = next(ln for ln in out.splitlines() if str(mem) in ln and ln.startswith("note:"))
        assert "its own memory" not in line
        assert f"memory init --path {folder.parent / (folder.name + '.memory')}" in line
        assert f"cp -R {mem} " in line


def test_each_claimant_hears_it_once_at_load_and_always_in_check(
    first, mem, capsys, tmp_path, monkeypatch
):
    copy = copy_of(first, tmp_path)
    moved_from(first, tmp_path)
    monkeypatch.chdir(copy)
    assert str(mem) in next(ln for ln in run(capsys, "load")[1].splitlines() if "gone" in ln)
    assert not [ln for ln in run(capsys, "load")[1].splitlines() if "is gone" in ln]
    for _ in range(2):
        code, out = run(capsys, "check", "--strict")
        assert code == 0 and "is gone" in out


def test_an_add_in_a_copy_hears_it_when_no_load_came_first(
    first, mem, capsys, tmp_path, monkeypatch
):
    copy = copy_of(first, tmp_path)
    moved_from(first, tmp_path)
    monkeypatch.chdir(copy)
    _, out = run(capsys, "add", "from the copy", "--basis", "seen", "--source", "s:1")
    assert "is gone" in out


def test_a_plain_move_hears_nothing_and_takes_nothing(first, mem, capsys, tmp_path, monkeypatch):
    before = owner(mem)
    moved = moved_from(first, tmp_path)
    monkeypatch.chdir(moved)
    _, out = run(capsys, "load")
    assert FACT in out and "is gone" not in out
    assert owner(mem) == before
    code, out = run(capsys, "check", "--strict")
    assert code == 0 and "is gone" not in out


def test_a_session_start_takes_nothing(first, mem, capsys, tmp_path, monkeypatch):
    before = owner(mem)
    moved = moved_from(first, tmp_path)
    monkeypatch.chdir(moved)
    code, out = run(capsys, "hook", "session-start", "--agent", "pi")
    assert code == 0 and FACT in out
    assert owner(mem) == before


def test_init_takes_it_and_the_other_repo_keeps_its_facts(
    first, mem, capsys, tmp_path, monkeypatch
):
    copy = copy_of(first, tmp_path)
    moved = moved_from(first, tmp_path)
    monkeypatch.chdir(moved)
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert owner(mem) == key(moved)
    _, out = run(capsys, "load")
    assert FACT in out and str(copy) not in out
    monkeypatch.chdir(copy)
    _, out = run(capsys, "load")
    assert FACT in out and str(moved) in out and "belongs to another project" in out
    assert not (tmp_path / "copy.memory").exists()


def test_when_the_copy_takes_it_the_real_repo_gets_no_empty_fix(
    first, mem, capsys, tmp_path, monkeypatch
):
    copy = copy_of(first, tmp_path)
    moved = moved_from(first, tmp_path)
    monkeypatch.chdir(copy)
    assert run(capsys, "init", "--no-default-rules")[0] == 0
    assert owner(mem) == key(copy)
    monkeypatch.chdir(moved)
    _, out = run(capsys, "load")
    line = next(ln for ln in out.splitlines() if ln.startswith("note:") and str(mem) in ln)
    assert "this repo is a copy" not in line
    assert "its own memory" not in line
    assert f"cp -R {mem} {tmp_path / 'moved.memory'}" in line
    assert owner(mem) == key(copy)


def test_the_printed_fix_keeps_the_facts_and_ends_the_note(
    first, mem, capsys, tmp_path, monkeypatch
):
    copy = copy_of(first, tmp_path)
    moved = moved_from(first, tmp_path)
    monkeypatch.chdir(moved)
    assert run(capsys, "init", "--no-default-rules")[0] == 0
    monkeypatch.chdir(copy)
    _, out = run(capsys, "load")
    source, target = re.search(r"`cp -R (\S+) (\S+) && memory init --path \S+`", out).groups()
    shutil.copytree(source, target)
    code, out = run(capsys, "init", "--no-default-rules", "--path", target)
    assert code == 0, out
    _, out = run(capsys, "load")
    assert FACT in out and "belongs to another project" not in out
    assert (copy / "memory-bank").resolve() == (tmp_path / "copy.memory").resolve()
    assert owner(tmp_path / "copy.memory") == key(copy)
    assert owner(mem) == key(moved)
    monkeypatch.chdir(moved)
    _, out = run(capsys, "load")
    assert FACT in out and "copy" not in out.split("\n", 1)[0]


def test_stated_sharing_silences_the_line(first, mem, capsys, tmp_path, monkeypatch):
    copy = copy_of(first, tmp_path)
    moved_from(first, tmp_path)
    git(copy, "config", "cairnkit.sharedmemory", "true")
    monkeypatch.chdir(copy)
    _, out = run(capsys, "load")
    assert FACT in out and "is gone" not in out


def test_a_copy_with_a_live_owner_stays_a_copy_after_a_load(
    first, mem, capsys, tmp_path, monkeypatch
):
    before = owner(mem)
    copy = copy_of(first, tmp_path)
    monkeypatch.chdir(copy)
    _, out = run(capsys, "load")
    assert "belongs to another project" in out
    assert "memory init --path" in out and f"cp -R {mem}" in out
    assert owner(mem) == before


STEPS = ("cp", "mv", "load", "init")


@pytest.mark.parametrize("order", list(itertools.permutations(STEPS)), ids="-".join)
def test_every_order_of_cp_mv_load_and_init(first, mem, capsys, tmp_path, monkeypatch, order):
    real = first
    copy = None
    own_memory = False
    for step in order:
        if step == "cp":
            copy = copy_of(real, tmp_path)
        elif step == "mv":
            real = moved_from(real, tmp_path)
        else:
            monkeypatch.chdir(copy or real)
            before = owner(mem)
            code, out = run(capsys, step, *(["--no-default-rules"] if step == "init" else []))
            assert code == 0, out
            if step == "load":
                assert owner(mem) == before, "a load moved the owner"
            elif copy and read_identity(mem).owner == before and before.exists():
                own_memory = True

    monkeypatch.chdir(real)
    held = owner(mem)
    _, out = run(capsys, "load")
    assert FACT in out, "the real repo lost its memory"
    assert owner(mem) == held
    assert "this repo is a copy" not in out
    assert "gives this copy" not in out
    assert not (tmp_path / f"{real.name}.memory").exists()

    if copy is None:
        return
    monkeypatch.chdir(copy)
    _, out = run(capsys, "load")
    assert owner(mem) == held
    assert (FACT in out) != own_memory


def test_a_repo_that_comes_back_to_its_path_is_the_owner(first, mem, capsys, tmp_path, monkeypatch):
    moved = moved_from(first, tmp_path)
    moved.rename(first)
    monkeypatch.chdir(first)
    _, out = run(capsys, "load")
    assert FACT in out and "is gone" not in out
    assert owner(mem) == key(first)
