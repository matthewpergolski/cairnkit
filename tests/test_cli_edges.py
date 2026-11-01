"""Bad bytes, closed pipes, long names and piles of rules get a true result, not a Traceback."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from conftest import make_fact, read_jsonl, write_facts

from cairnkit.selection import NAME_WIDTH, RULE_WORD_LIMIT, name

FLAGS = ["--basis", "seen", "--source", "session:2026-11-01"]


def _run(cwd, *args, env=None):
    return subprocess.run(
        [os.fsencode(sys.executable), b"-m", b"cairnkit", *map(os.fsencode, args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
    )


def _rules(mem, count, words=20):
    body = " ".join(["word"] * (words - 1))
    write_facts(
        mem,
        [
            make_fact(f"f-20261001-{i:04x}", f"Rule{i} {body}", kind="rule", basis="told")
            for i in range(count)
        ],
    )


def test_a_text_that_is_not_utf8_gets_a_clean_error(mem, repo):
    done = _run(repo, "add", "caf\udce9", *FLAGS)
    assert done.returncode == 1
    assert "Traceback" not in done.stderr
    assert "UTF-8" in done.stderr
    assert not (mem / "facts" / "main.jsonl").read_text()


def test_a_read_only_fact_folder_gets_a_clean_error_and_the_load_still_works(mem, repo):
    write_facts(mem, [make_fact("f-20261001-0001", "A readable fact.")])
    facts = mem / "facts"
    modes = {path: path.stat().st_mode for path in [facts, *facts.iterdir()]}
    for path in modes:
        path.chmod(path.stat().st_mode & ~0o222)
    try:
        done = _run(repo, "add", "A fact with nowhere to go.", *FLAGS)
        loaded = _run(repo, "load")
    finally:
        for path, mode in modes.items():
            path.chmod(mode)
    if os.geteuid() == 0:
        pytest.skip("root ignores file modes")
    assert done.returncode == 1
    assert "Traceback" not in done.stderr
    assert done.stderr.startswith("error: ")
    assert "added" not in done.stdout
    assert loaded.returncode == 0
    assert "A readable fact." in loaded.stdout


@pytest.mark.parametrize("content", [b"\xff\xfe", b"\x00", b""])
def test_a_bad_memory_path_file_does_not_stop_a_command(mem, repo, content):
    (repo / ".memory-path").write_bytes(content)
    write_facts(mem, [make_fact("f-20261001-0001", "Still here.")])
    loaded = _run(repo, "load")
    assert loaded.returncode == 0
    assert "Still here." in loaded.stdout
    added = _run(repo, "add", "Added with a bad path file.", *FLAGS)
    assert "Traceback" not in added.stderr
    assert added.returncode == 0, added.stderr
    assert "Added with a bad path file." in (mem / "facts" / "main.jsonl").read_text()
    checked = _run(repo, "check")
    assert "Traceback" not in checked.stderr


def test_check_names_a_memory_path_file_that_is_not_text(mem, repo):
    (repo / ".memory-path").write_bytes(b"\xff\xfe")
    done = _run(repo, "check")
    assert ".memory-path" in done.stdout + done.stderr


def test_a_load_from_a_deleted_folder_exits_0(tmp_path):
    folder = tmp_path / "gone"
    folder.mkdir()
    script = (
        "import os, sys\n"
        f"os.chdir({str(folder)!r})\n"
        f"os.rmdir({str(folder)!r})\n"
        "from cairnkit.cli import main\n"
        "sys.exit(main(sys.argv[1:]))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script, "load"], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0
    assert "Traceback" not in done.stderr
    assert "memory: not loaded" in done.stdout


def _closed_pipe(repo, *args):
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        return subprocess.run(
            [sys.executable, "-m", "cairnkit", *args],
            cwd=repo,
            stdout=write_end,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
    finally:
        os.close(write_end)


def test_a_closed_pipe_after_a_write_exits_0(mem, repo):
    text = "A fact whose reader went away."
    done = _closed_pipe(repo, "add", text, *FLAGS)
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    assert text in (mem / "facts" / "main.jsonl").read_text()


def test_a_closed_pipe_keeps_a_refusal_exit_code(mem, repo):
    done = _closed_pipe(repo, "add", "password=hunter2hunter2", *FLAGS)
    assert done.returncode == 1


def test_a_load_into_a_closed_pipe_exits_0(mem, repo):
    write_facts(mem, [make_fact(f"f-20261001-{i:04x}", f"Fact {i} " + "w" * 900) for i in range(40)])
    done = _closed_pipe(repo, "load", "--budget", "0")
    assert done.returncode == 0, done.stderr
    assert done.stderr == ""


def test_a_search_into_a_closed_pipe_says_so_in_the_exit_code(mem, repo):
    write_facts(mem, [make_fact(f"f-20261001-{i:04x}", f"Fact {i} " + "w" * 900) for i in range(40)])
    done = _closed_pipe(repo, "search", "Fact")
    assert done.returncode == 141
    assert "Traceback" not in done.stderr


@pytest.mark.parametrize("value", ["a" * 5000, "a b " * 1000, "a" * (NAME_WIDTH + 1)])
def test_a_long_stored_name_is_bounded_at_the_display(value):
    assert len(name(value)) <= NAME_WIDTH + 2


def test_a_plain_short_name_prints_as_it_is():
    assert name("billing") == "billing"


def test_a_long_area_keeps_its_full_text_on_disk_and_a_short_load_line(mem, repo):
    area = "a" * 5000
    done = _run(repo, "add", "x", "--area", area, *FLAGS)
    assert done.returncode == 0, done.stderr
    assert read_jsonl(mem / "facts" / "main.jsonl")[0]["area"] == area
    loaded = _run(repo, "load")
    assert max(len(line) for line in loaded.stdout.splitlines()) < 400
    done = _run(repo, "tidy")
    assert done.returncode == 0


def test_a_long_area_is_bounded_in_the_agent_task(mem, repo):
    area = "a" * 5000
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "The same words here today", area=area),
            make_fact("f-20261002-0002", "the same words here today", area=area),
        ],
    )
    assert _run(repo, "tidy").returncode == 0
    task = (mem / "proposals" / "tidy-followups.md").read_text()
    assert area not in task


def test_a_small_budget_says_that_rules_are_outside_it(mem, repo):
    _rules(mem, 3)
    loaded = _run(repo, "load", "--budget", "10")
    lines = [line for line in loaded.stdout.splitlines() if "outside the word budget" in line]
    assert len(lines) == 1
    assert "3 rule(s)" in lines[0]
    assert sum("Rule" in line and line.startswith("- [") for line in loaded.stdout.splitlines()) == 3


def test_a_default_load_with_few_rules_has_no_rule_note(mem, repo):
    _rules(mem, 3)
    loaded = _run(repo, "load")
    assert "outside the word budget" not in loaded.stdout
    assert "held back" not in loaded.stdout


def test_a_pile_of_rules_is_bounded_and_says_what_it_held_back(mem, repo):
    _rules(mem, 80)
    loaded = _run(repo, "load", "--budget", "50")
    shown = [line for line in loaded.stdout.splitlines() if line.startswith("- [")]
    assert sum(len(line.split()) for line in shown) <= RULE_WORD_LIMIT
    assert len(shown) < 80
    note = next(line for line in loaded.stdout.splitlines() if "rule(s) held back" in line)
    assert f"{80 - len(shown)} rule(s) held back" in note
    assert "memory load --budget 0" in note
    assert f"{80 - len(shown)} active fact(s) not shown" in loaded.stdout


def test_budget_0_prints_every_rule(mem, repo):
    _rules(mem, 80)
    loaded = _run(repo, "load", "--budget", "0")
    assert sum(line.startswith("- [") for line in loaded.stdout.splitlines()) == 80
    assert "held back" not in loaded.stdout


def test_a_rule_that_only_a_load_can_enforce_goes_before_the_rest(mem, repo):
    enforced = [
        make_fact(
            f"f-20261001-{i:04x}",
            f"Enforced{i} " + "word " * 40,
            kind="rule",
            basis="told",
            enforced_by="ci:x",
        )
        for i in range(60)
    ]
    advisory = make_fact(
        "f-20261009-0001",
        "Advisory rule that came last.",
        kind="rule",
        basis="told",
        learned_at="2026-10-09T00:00:00+00:00",
    )
    write_facts(mem, [*enforced, advisory])
    loaded = _run(repo, "load")
    assert "Advisory rule that came last." in loaded.stdout
    assert "rule(s) held back" in loaded.stdout


def test_presets_all_fit_under_the_rule_limit(mem, repo):
    assert _run(repo, "preset", "add", "dev").returncode == 0
    loaded = _run(repo, "load")
    assert "held back" not in loaded.stdout
    assert RULE_WORD_LIMIT >= 2 * 368
