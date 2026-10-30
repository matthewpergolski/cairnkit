"""The rename from project-memory to cairnkit.

Repos that an older version set up hold the old marker names. Each writer finds
an old block and replaces it in place with one new block. It never adds a
second block.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from cairnkit import __version__, adapters, githook, instruction_files, instructions, refresh, tidy
from cairnkit.cli import main
from cairnkit.paths import find_project

OLD_START = "<!-- project-memory:start -->"
OLD_END = "<!-- project-memory:end -->"
OLD_RULES_START = "<!-- project-memory:rules:start -->"
OLD_RULES_END = "<!-- project-memory:rules:end -->"
OLD_HOOK_START = "# >>> project-memory >>>"
OLD_HOOK_END = "# <<< project-memory <<<"
OLD_COMMAND = "/old/python -m project_memory hook session-start --agent claude"


def old_rules_block(body: str = "Old text.") -> str:
    return f"{OLD_START}\n## Project memory\n\n{body}\n{OLD_END}\n"


def test_new_markers_name_cairnkit():
    assert instructions.START == "<!-- cairnkit:start -->"
    assert tidy.RULES_START == "<!-- cairnkit:rules:start -->"
    assert githook.START == "# >>> cairnkit >>>"
    assert "-m cairnkit hook" in adapters.hook_command("stop", "claude")


def test_both_console_scripts_run_the_same_cli():
    data = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    assert data["project"]["name"] == "cairnkit"
    scripts = data["project"]["scripts"]
    assert scripts["cairnkit"] == scripts["memory"] == "cairnkit.cli:main"


def test_write_instructions_migrates_an_old_marker_block_out_of_tracked(repo):
    agents = repo / "AGENTS.md"
    agents.write_text(f"top\n\n{old_rules_block()}\nbottom\n")
    for _ in range(2):
        assert main(["instructions", "--write-instructions"]) == 0
    text = agents.read_text()
    assert OLD_START not in text and OLD_END not in text
    assert instructions.START not in text
    assert "Old text." not in text
    assert text.startswith("top\n\n") and text.endswith("\nbottom\n")
    local = (repo / "CLAUDE.local.md").read_text()
    assert local.count(instructions.START) == 1 and instructions.block() in local


def test_refresh_migrates_an_old_marker_block_out_of_tracked(repo):
    assert main(["init"]) == 0
    agents = repo / "AGENTS.md"
    agents.write_text(f"# Team\n\n{old_rules_block()}\nMore.\n")
    project = find_project()
    assert refresh.repo_line(project, None)  # an old block is found
    assert main(["init", "--refresh"]) == 0
    first = agents.read_text()
    assert OLD_START not in first and instructions.START not in first
    assert first.startswith("# Team\n\n") and first.endswith("\nMore.\n")
    assert main(["init", "--refresh"]) == 0
    assert agents.read_text() == first


def test_an_old_and_a_new_block_together_are_refused(repo, capsys):
    agents = repo / "AGENTS.md"
    text = old_rules_block() + "\n" + instructions.block()
    agents.write_text(text)
    assert main(["instructions", "--write-instructions"]) == 1
    assert agents.read_text() == text
    assert "by hand" in capsys.readouterr().out


def test_an_old_block_is_skipped_when_reading_hand_written_rules(repo):
    (repo / "AGENTS.md").write_text(
        old_rules_block("- Always write a fact.") + "\n- Use the staging server first.\n"
    )
    texts = [" ".join(w for s in i.sentences for w in s) for i in instruction_files.items(repo)]
    assert any("staging server" in t for t in texts)
    assert not any("always write a fact" in t for t in texts)


def test_tidy_adds_a_rule_inside_an_old_block_and_renames_its_markers(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"top\n{OLD_RULES_START}\n## Rules\n\n- One.\n{OLD_RULES_END}\nbottom\n")
    tidy.add_rule(path, "Two.")
    tidy.add_rule(path, "Two.")
    text = path.read_text()
    assert OLD_RULES_START not in text and OLD_RULES_END not in text
    assert text.count(tidy.RULES_START) == 1 and text.count(tidy.RULES_END) == 1
    assert text.count("- Two.\n") == 1 and "- One.\n" in text
    assert text.startswith("top\n") and text.endswith("bottom\n")


def test_git_hook_with_old_markers_gets_one_new_block(repo, capsys):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\n{OLD_HOOK_START}\nold body\n{OLD_HOOK_END}\necho team-check\n")
    hook.chmod(0o755)
    for _ in range(2):
        assert main(["hooks", "install", "--agent", "generic"]) == 0
    text = hook.read_text()
    assert OLD_HOOK_START not in text and "old body" not in text
    assert text.count(githook.START) == 1 and text.count(githook.END) == 1
    assert text.endswith("echo team-check\n")
    assert main(["hooks", "uninstall"]) == 0
    assert hook.read_text() == "#!/bin/sh\necho team-check\n"


def test_uninstall_removes_an_old_marker_git_hook_block(repo):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\n{OLD_HOOK_START}\nold body\n{OLD_HOOK_END}\necho mine\n")
    assert main(["hooks", "uninstall"]) == 0
    assert hook.read_text() == "#!/bin/sh\necho mine\n"


def test_refresh_rewrites_old_agent_hooks_and_old_git_hooks(repo):
    assert main(["init"]) == 0
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps(
            {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": OLD_COMMAND}]}]}}
        )
    )
    shared = repo / ".githooks" / "commit-msg"
    shared.parent.mkdir()
    shared.write_text(f"#!/bin/sh\n{OLD_HOOK_START}\nold guard\n{OLD_HOOK_END}\n")
    assert refresh.repo_line(find_project(), None)
    assert main(["init", "--refresh"]) == 0
    data = json.loads(settings.read_text())
    commands = [h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"]]
    assert commands == [adapters.hook_command("session-start", "claude")]
    text = shared.read_text()
    assert OLD_HOOK_START not in text and text.count(githook.START) == 1
    assert githook.GUARD_MARK in text


def test_hooks_uninstall_removes_old_agent_hooks(repo):
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    mine = {"type": "command", "command": "echo mine"}
    old = {"type": "command", "command": OLD_COMMAND}
    settings.write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [mine, old]}]}}))
    assert main(["hooks", "uninstall"]) == 0
    data = json.loads(settings.read_text())
    assert data == {"hooks": {"SessionStart": [{"hooks": [mine]}]}}


@pytest.mark.parametrize("name", ["cairnkit", "memory"])
def test_each_command_names_itself(name, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", [f"/tools/bin/{name}"])
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out == f"{name} {__version__}\n"
