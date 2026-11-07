"""The "facts that match the files you changed" hint skips work that landed and shows at most 2."""

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


def test_the_hint_skips_landed_work_and_shows_two(repo, mem, capsys, monkeypatch):
    at(monkeypatch, "05")
    commit(repo, "app", {"src/app.py": "v1\n"})
    at(monkeypatch, "10")
    done = [
        add(capsys, "Yes to the app split.", "--kind", "decision", "--files", "src/app.py"),
        add(capsys, "The app split is under way.", "--files", "src/app.py"),
    ]
    lessons = [
        add(
            capsys,
            f"App lesson {n}: keep imports lazy.",
            "--kind",
            "lesson",
            "--files",
            "src/app.py",
        )
        for n in range(3)
    ]
    at(monkeypatch, "12")
    commit(repo, "Land the app split", {"src/app.py": "v2\n"})
    at(monkeypatch, "13")
    hook(capsys, monkeypatch, "session-start", source="startup")
    path = mem / ".sessions" / "s.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["shown"] = []
    path.write_text(json.dumps(state), encoding="utf-8")
    (repo / "src" / "app.py").write_text("v3\n")
    text = hook(capsys, monkeypatch, "prompt")
    assert "match the files you changed" in text
    assert not any(fid in text for fid in done), "their work landed"
    shown = re.findall(r"^- \[(f-\S+)\]", text, re.MULTILINE)
    assert len(shown) == 2 and set(shown) < set(lessons)
    assert "and 1 more" in text
