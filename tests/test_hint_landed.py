"""The "facts that match the files you changed" hint skips only a one-time approval whose work
landed, and shows at most 2."""

from __future__ import annotations

import io
import json
import re

from test_landed import add, at, commit

from cairnkit.cli import main


def hook(capsys, monkeypatch, event, **payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s", **payload})))
    capsys.readouterr()
    main(["hook", event, "--agent", "claude"])
    return capsys.readouterr().out


def start_then_edit(repo, mem, capsys, monkeypatch, rel: str) -> str:
    """A session starts, forgets what it showed, and the agent edits `rel`. The prompt hint."""
    at(monkeypatch, "13")
    hook(capsys, monkeypatch, "session-start", source="startup")
    path = mem / ".sessions" / "s.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["shown"] = []
    path.write_text(json.dumps(state), encoding="utf-8")
    (repo / rel).write_text("edited\n")
    return hook(capsys, monkeypatch, "prompt")


def test_the_hint_skips_landed_work_and_shows_two(repo, mem, capsys, monkeypatch):
    at(monkeypatch, "05")
    commit(repo, "app", {"src/app.py": "v1\n"})
    at(monkeypatch, "10")
    done = add(capsys, "Yes to the app split.", "--kind", "decision", "--files", "src/app.py")
    rest = [add(capsys, "The app split is under way.", "--files", "src/app.py")]
    rest += [
        add(
            capsys,
            f"App lesson {n}: keep imports lazy.",
            "--kind",
            "lesson",
            "--files",
            "src/app.py",
        )
        for n in range(2)
    ]
    at(monkeypatch, "12")
    commit(repo, "Land the app split", {"src/app.py": "v2\n"})
    text = start_then_edit(repo, mem, capsys, monkeypatch, "src/app.py")
    assert "match the files you changed" in text
    assert done not in text, "its work landed"
    shown = re.findall(r"^- \[(f-\S+)\]", text, re.MULTILINE)
    assert len(shown) == 2 and set(shown) < set(rest)
    assert "and 1 more" in text


def test_a_told_decision_shows_when_its_file_changes(repo, mem, capsys, monkeypatch):
    at(monkeypatch, "05")
    commit(repo, "base", {"pyproject.toml": "[project]\n"})
    at(monkeypatch, "10")
    told = add(
        capsys,
        "Pin the build backend in pyproject.toml to hatchling.",
        "--kind",
        "decision",
        "--basis",
        "told",
        "--files",
        "pyproject.toml",
    )
    at(monkeypatch, "12")
    commit(repo, "bump the version", {"pyproject.toml": "[project]\nversion = '2'\n"})
    text = start_then_edit(repo, mem, capsys, monkeypatch, "pyproject.toml")
    assert told in text, "a lasting decision holds after a change to its file"
