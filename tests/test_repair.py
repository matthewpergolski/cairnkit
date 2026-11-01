"""A problem blocks a stop once, names its command, and has a fix with no hand edit and no purge."""

from __future__ import annotations

import io
import json

import pytest
from conftest import git, make_fact, write_facts

from cairnkit.cli import main
from cairnkit.config import load_config

GOOD = "f-20261001-0001"
HELD = "f-20261001-0002"


def _run(capsys, *command):
    capsys.readouterr()
    code = main(list(command))
    return code, capsys.readouterr().out


def _stop(capsys, monkeypatch, session="s1"):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": session})))
    capsys.readouterr()
    assert main(["hook", "stop", "--agent", "claude"]) == 0
    out = capsys.readouterr().out
    return json.loads(out) if out.strip() else {}


def _append(mem, text):
    with (mem / "facts" / "main.jsonl").open("a") as fh:
        fh.write(text)


def _gone_held_by(mem):
    write_facts(
        mem,
        [
            make_fact(HELD, "A true fact that another file was said to hold."),
            {
                "type": "change",
                "id": HELD,
                "at": "2026-10-02T12:00:00+00:00",
                "status": "promoted",
                "held_by": "docs/gone-for-good.md",
                "reason": "Moved.",
                "writer": "main",
            },
        ],
    )


@pytest.mark.parametrize("text", ['{"typ', '{"type":"fact"}\n', "not json at all\n"])
def test_a_bad_line_blocks_once_and_gives_the_command(mem, capsys, monkeypatch, text):
    write_facts(mem, [make_fact(GOOD, "A true fact.")])
    _append(mem, text)
    first = _stop(capsys, monkeypatch)
    assert first["decision"] == "block"
    assert "`memory repair`" in first["reason"]
    assert "memory check --strict" in first["reason"]
    for session in ("s1", "s2"):
        later = _stop(capsys, monkeypatch, session)
        assert "memory repair" not in later.get("reason", "")


def test_a_new_problem_blocks_again(mem, capsys, monkeypatch):
    _append(mem, '{"typ\n')
    _stop(capsys, monkeypatch)
    assert _stop(capsys, monkeypatch).get("decision") != "block"
    _append(mem, '{"type":"fact"}\n')
    second = _stop(capsys, monkeypatch)
    assert second["decision"] == "block"
    assert "main.jsonl:2" in second["reason"]
    assert "main.jsonl:1" not in second["reason"]


def test_repair_clears_a_bad_line_and_keeps_every_byte(mem, capsys):
    write_facts(mem, [make_fact(GOOD, "A true fact.", pinned=True)])
    _append(mem, '{"typ\n')
    path = mem / "facts" / "main.jsonl"
    before = path.read_bytes()
    assert _run(capsys, "check", "--strict")[0] == 1
    code, out = _run(capsys, "repair")
    assert code == 0
    assert "main.jsonl:2" in out
    assert '{"typ' in out, "the agent can read what was lost"
    assert path.read_bytes().startswith(before)
    assert _run(capsys, "check", "--strict")[0] == 0
    code, load = _run(capsys, "load")
    assert "bad line" not in load and "A true fact." in load


def test_a_repair_record_copies_no_text_from_the_line(mem, capsys):
    line = {
        "type": "fact",
        "id": GOOD,
        "text": "Old.",
        "source": "NOT A SOURCE CRON_SECRET=q1w2e3r4",
    }
    _append(mem, json.dumps(line) + "\n")
    _run(capsys, "repair")
    written = (mem / "facts" / "main.jsonl").read_text().splitlines()[-1]
    assert json.loads(written)["type"] == "repair"
    assert "q1w2e3r4" not in written


def test_repair_is_safe_to_repeat(mem, capsys):
    _append(mem, '{"typ\n')
    assert _run(capsys, "repair")[0] == 0
    path = mem / "facts" / "main.jsonl"
    size = path.stat().st_size
    code, out = _run(capsys, "repair")
    assert code == 0 and "Nothing to repair." in out
    assert path.stat().st_size == size


def test_repair_does_not_cover_a_new_bad_line(mem, capsys):
    _append(mem, '{"typ\n')
    _run(capsys, "repair")
    _append(mem, '{"other\n')
    assert _run(capsys, "check", "--strict")[0] == 1
    assert "1 bad line(s)" in _run(capsys, "load")[1]


def test_repair_clears_a_record_with_a_schema_problem_and_keeps_its_fact(mem, capsys):
    _append(
        mem, json.dumps({"type": "fact", "id": GOOD, "text": "An old fact, still true."}) + "\n"
    )
    assert _run(capsys, "check", "--strict")[0] == 1
    assert _run(capsys, "repair")[0] == 0
    assert _run(capsys, "check", "--strict")[0] == 0
    assert "An old fact, still true." in _run(capsys, "load")[1]


def test_repair_clears_a_writer_that_differs_from_the_file(mem, capsys):
    write_facts(mem, [make_fact(GOOD, "A true fact.", writer="someone-else")])
    assert _run(capsys, "check", "--strict")[0] == 1
    assert _run(capsys, "repair")[0] == 0
    assert _run(capsys, "check", "--strict")[0] == 0


def test_repair_leaves_a_secret_for_purge_and_says_how(mem, capsys):
    write_facts(mem, [make_fact(GOOD, "CRON_SECRET=q1w2e3r4t5y6a8s9")])
    code, out = _run(capsys, "repair")
    assert code == 1
    assert f"memory purge {GOOD}" in out
    assert "q1w2e3r4t5y6a8s9" not in out
    assert _run(capsys, "check", "--strict")[0] == 1


def test_a_gone_held_by_names_a_fix_with_no_purge(mem, repo, capsys, monkeypatch):
    _gone_held_by(mem)
    code, out = _run(capsys, "check", "--strict")
    assert code == 1
    assert f"memory change {HELD} --status active" in out
    assert "purge" not in out
    first = _stop(capsys, monkeypatch)
    assert first["decision"] == "block"
    assert f"memory change {HELD} --status active" in first["reason"]
    assert _stop(capsys, monkeypatch).get("decision") != "block"
    assert main(["change", HELD, "--status", "active", "--reason", "The file is gone."]) == 0
    assert _run(capsys, "check", "--strict")[0] == 0
    assert "A true fact that another file" in _run(capsys, "load")[1]


def test_a_later_good_held_by_clears_the_problem(mem, repo, capsys):
    _gone_held_by(mem)
    assert (
        main(["change", HELD, "--status", "promoted", "--held-by", "README.md", "--reason", "x"])
        == 0
    )
    assert _run(capsys, "check", "--strict")[0] == 0


def test_a_held_by_in_the_history_of_a_branch_is_still_fine(mem, repo, capsys):
    git(repo, "switch", "-qc", "feat")
    (repo / "only-on-feat.md").write_text("x")
    git(repo, "add", "only-on-feat.md")
    git(repo, "commit", "-qm", "feat")
    assert main(["add", "A rule held on feat.", "--basis", "seen", "--source", "session:1"]) == 0
    fid = capsys.readouterr().out.split()[-1]
    assert (
        main(
            ["change", fid, "--status", "promoted", "--held-by", "only-on-feat.md", "--reason", "r"]
        )
        == 0
    )
    git(repo, "switch", "-q", "main")
    assert _run(capsys, "check", "--strict")[0] == 0


@pytest.mark.parametrize(
    "text,mode",
    [
        ('auto_tidy = "off"\n[areas\n', "off"),
        ('auto_tidy = "of"\n', "off"),
        ('auto_tidyy = "off"\n', "off"),
        (b'auto_tidy = "report"\n# caf\xe9\n', "report"),
        ("[areas\n", "auto"),
        ("skills_check = 5\n", "auto"),
        ("[commit_msg_guard]\npatterns = 5\n", "auto"),
        ("auto_tidy = 1\n", "off"),
    ],
)
def test_repair_fixes_a_config_and_keeps_the_good_lines(mem, capsys, text, mode):
    path = mem / "config.toml"
    raw = text if isinstance(text, bytes) else text.encode()
    path.write_bytes(raw)
    assert _run(capsys, "check", "--strict")[0] == 1
    assert _run(capsys, "repair")[0] == 0
    assert _run(capsys, "check", "--strict")[0] == 0
    assert load_config(mem)["auto_tidy"] == mode
    assert (mem / "config.toml.bad").read_bytes() == raw


def test_repair_keeps_an_area_table_in_a_config(mem, capsys):
    (mem / "config.toml").write_text('auto_tidy = 5\n[areas]\n"src/" = "core"\n')
    assert _run(capsys, "repair")[0] == 0
    assert load_config(mem)["areas"] == {"src/": "core"}
    assert load_config(mem)["auto_tidy"] == "off"


def test_a_good_memory_has_nothing_to_repair(mem, capsys):
    write_facts(mem, [make_fact(GOOD, "A true fact.")])
    before = (mem / "facts" / "main.jsonl").read_bytes()
    code, out = _run(capsys, "repair")
    assert code == 0 and "Nothing to repair." in out
    assert (mem / "facts" / "main.jsonl").read_bytes() == before
