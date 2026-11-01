"""Every write of a fact file takes one lock, so a fact that was reported added stays."""

from __future__ import annotations

import contextlib
import fcntl
import os
import subprocess
import sys
from argparse import Namespace

from conftest import make_fact, read_jsonl, write_facts

from cairnkit import store
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project
from cairnkit.writing import add_fact

TARGET = "f-20261001-0001"
FLAGS = ["--basis", "seen", "--source", "session:2026-11-01"]


def _add_process(repo, text):
    return subprocess.Popen(
        [sys.executable, "-m", "cairnkit", "add", text, *FLAGS],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _active(text):
    states = Memory.open(find_project(), None).states.values()
    return [s for s in states if s["status"] == "active" and s["text"] == text]


def test_a_purge_keeps_a_fact_added_during_its_rewrite(mem, repo, monkeypatch, capsys):
    write_facts(mem, [make_fact(TARGET, "Purge this one.")])
    text = "A fact added during the rewrite."
    real_replace = os.replace
    adders = []

    def replace(src, dst):
        adders.append(_add_process(repo, text))
        with contextlib.suppress(subprocess.TimeoutExpired):
            adders[0].wait(timeout=1.0)
        real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", replace)
    assert main(["purge", TARGET, "--reason", "test", "--yes"]) == 0
    out, err = adders[0].communicate(timeout=30)
    assert adders[0].returncode == 0, err
    assert "added" in out
    assert text in (mem / "facts" / "main.jsonl").read_text()


def test_a_purge_waits_for_a_held_lock_and_reads_the_file_inside_it(mem, repo, capsys):
    write_facts(mem, [make_fact(TARGET, "Purge this one.")])
    with store.locked(mem / "facts" / store.WRITE_LOCK):
        process = subprocess.Popen(
            [sys.executable, "-m", "cairnkit", "purge", TARGET, "--reason", "t", "--yes"],
            cwd=repo,
            stdout=subprocess.PIPE,
            text=True,
        )
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=0.5)
        assert process.poll() is None
        write_facts(mem, [make_fact("f-20261001-0002", "Written while the purge waited.")])
    process.communicate(timeout=30)
    assert process.returncode == 0
    text = (mem / "facts" / "main.jsonl").read_text()
    assert "Written while the purge waited." in text
    assert "Purge this one." not in text


def test_a_nested_write_does_not_wait_on_its_own_lock(mem):
    path = mem / "facts" / "main.jsonl"
    with store.write_lock(mem):
        store.append_records(path, [make_fact(TARGET, "Inside the lock.")])
    assert [r["id"] for r in read_jsonl(path)] == [TARGET]


def test_a_write_lock_can_be_taken_again_after_it_ends(mem):
    lock = mem / "facts" / store.WRITE_LOCK
    with store.write_lock(mem):
        pass
    with lock.open("ab") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(held, fcntl.LOCK_UN)


def test_parallel_identical_adds_leave_one_active_fact(mem, repo):
    text = "Eight sessions learn the same thing at once."
    adders = [_add_process(repo, text) for _ in range(8)]
    for adder in adders:
        _, err = adder.communicate(timeout=60)
        assert adder.returncode == 0, err
    assert len(_active(text)) == 1


def test_parallel_identical_rule_adds_write_one_rule(mem, repo):
    text = "Never deploy on a Friday."
    adders = [
        subprocess.Popen(
            [sys.executable, "-m", "cairnkit", "add", text, "--kind", "rule", *FLAGS],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]
    outs = [adder.communicate(timeout=60)[0] for adder in adders]
    assert sum("already exists" in out for out in outs) == 3
    assert len(_active(text)) == 1


def test_an_add_reads_a_repeat_that_landed_after_the_memory_opened(mem, repo, capsys):
    text = "This fact arrives while the add looks."
    memory = Memory.open(find_project(), None)
    write_facts(mem, [make_fact(TARGET, text)])
    args = Namespace(
        text=text, kind="fact", area="general", basis="seen", source="session:x", summary=None,
        tag=None, link=None, pinned=False, enforced_by=None, expires=None, short=False,
        until_merged=None, supersedes=None, reason=None, happened_at=None,
    )  # fmt: skip
    assert add_fact(memory, args)
    assert "has the same words" in capsys.readouterr().out
    memory.reload()
    assert memory.states[TARGET]["status"] == "superseded"
