"""A name of 256 or more characters in a stored fact never costs the session its memory.

Python 3.12 raises ENAMETOOLONG from `Path.exists`, `Path.is_dir` and `Path.is_file` for such a
name, and later versions return False. A probe on the load path that let it out lost the whole
load: "memory: not loaded". The `strict_probes` fixture makes any Python act as 3.12 does.
"""

from __future__ import annotations

import errno
import io
import json
from pathlib import Path

import pytest
from conftest import make_fact, write_facts

from cairnkit.cli import main

LONG = "a" * 300


def _too_long(path: Path) -> bool:
    return any(len(part) > 255 for part in Path(path).parts)


@pytest.fixture
def strict_probes(monkeypatch):
    for name in ("exists", "is_dir", "is_file"):
        real = getattr(Path, name)

        def probe(self, *args, _real=real, **kwargs):
            if _too_long(self):
                raise OSError(errno.ENAMETOOLONG, "File name too long", str(self))
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, probe)


def long_facts(mem) -> None:
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", f"Yes to the change of {LONG}.py.", kind="decision"),
            make_fact("f-20261001-0002", "Read the long file.", source=f"file:{LONG}/x.py"),
            make_fact(
                "f-20261001-0003",
                "Run the long test.",
                kind="rule",
                basis="told",
                enforced_by=f"test:{LONG}.py",
            ),
            make_fact(
                "f-20261001-0004",
                "Yes to the long work.",
                kind="decision",
                files=[f"{LONG}.py"],
            ),
        ],
    )


def run(capsys, *argv: str) -> str:
    capsys.readouterr()
    main(list(argv))
    return capsys.readouterr().out


def test_the_load_survives_a_long_name(mem, capsys, strict_probes):
    long_facts(mem)
    out = run(capsys, "load")
    assert "not loaded" not in out
    assert "Read the long file." in out


def test_the_session_start_survives_a_long_name(mem, capsys, monkeypatch, strict_probes):
    long_facts(mem)
    (mem / "config.toml").write_text('auto_tidy = "on"\n')
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s1"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    out = capsys.readouterr().out
    assert "not loaded" not in out and "Read the long file." in out


def test_check_and_tidy_survive_a_long_name(mem, capsys, strict_probes):
    long_facts(mem)
    write_facts(
        mem,
        [
            make_fact(
                "f-20261001-0005", "Held in a long file.", status="promoted", held_by=f"{LONG}.md"
            )
        ],
        name="other.jsonl",
    )
    assert "Traceback" not in run(capsys, "check")
    assert "Traceback" not in run(capsys, "tidy")
