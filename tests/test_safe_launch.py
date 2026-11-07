"""Each launch of the tool imports nothing from the folder it runs in.

Hooks run in the session folder, and git runs its hooks in the work tree. That folder holds
files that a pull, a merge or an agent can write. Python puts the folder of `-m` and `-c` first
on the import path unless `-P` says not to.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import git

from cairnkit import adapters, githook, install_source, refresh
from cairnkit.cli import main
from cairnkit.paths import find_project

PLANTS = {
    "package": {
        "cairnkit/__init__.py": "import pathlib; pathlib.Path({out!r}).touch()\n",
        "cairnkit/__main__.py": "import pathlib; pathlib.Path({out!r}).touch()\n",
    },
    "stdlib": {"json.py": "import pathlib; pathlib.Path({out!r}).touch()\n"},
}


def plant(folder: Path, kind: str, marker: Path) -> None:
    for rel, text in PLANTS[kind].items():
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.format(out=str(marker)))


def fired(marker: Path) -> bool:
    found = marker.exists()
    marker.unlink(missing_ok=True)
    return found


def env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "PYTHONSAFEPATH"}


def run_shell(command: str, cwd: Path, *args: str) -> None:
    subprocess.run(
        ["sh", "-c", command, "hook", *args],
        cwd=cwd,
        input="{}",
        capture_output=True,
        text=True,
        timeout=60,
        env=env(),
    )


def agent_commands() -> list[str]:
    found: set[str] = set()
    for adapter in adapters.ADAPTERS.values():
        if not isinstance(adapter, adapters.FileAdapter):
            found.update(adapters._commands(adapter.add({})))
    return sorted(found)


def plugin_argv(name: str) -> list[str]:
    """The argv that a generated plugin passes to its Python, for one event."""
    text = adapters.ADAPTERS[name].render()
    python = json.loads(re.search(r"const PYTHON = (.+);", text)[1])
    args = re.search(r"const args = (\[.*?\]);", text)[1].replace("event", '"session-start"')
    return [python, *json.loads(args)]


@pytest.fixture(params=sorted(PLANTS))
def planted(request, repo, tmp_path) -> Path:
    marker = tmp_path / "MARKER"
    plant(repo, request.param, marker)
    return marker


def test_agent_hook_commands_import_nothing_from_the_session_folder(repo, planted):
    commands = agent_commands()
    assert commands
    ran = []
    for command in commands:
        run_shell(command, repo)
        ran += [command] if fired(planted) else []
    assert ran == []


@pytest.mark.parametrize("name", ["pi", "opencode"])
def test_generated_plugins_import_nothing_from_the_session_folder(repo, planted, name):
    argv = plugin_argv(name)
    subprocess.run(
        argv, cwd=repo, input="{}", capture_output=True, text=True, timeout=60, env=env()
    )
    assert not planted.exists(), argv


def test_git_hook_bodies_import_nothing_from_the_work_tree(repo, planted):
    git(repo, "config", "--local", "cairnkit.branchnotegate", "true")
    bodies = {
        "pre-commit": (githook.pre_commit_body(), ()),
        "pre-push": (githook.pre_push_body(None), ("origin", "url")),
        "post-merge": (githook.post_merge_body(), ("0",)),
        "post-checkout": (githook.post_checkout_body(), ("0" * 40, "1" * 40, "1")),
    }
    ran = []
    for hook, (body, args) in bodies.items():
        run_shell(body, repo, *args)
        ran += [hook] if fired(planted) else []
    assert ran == []


def test_the_background_update_check_imports_nothing_from_the_caller_folder(
    repo, planted, monkeypatch
):
    started: list[list[str]] = []
    with monkeypatch.context() as patch:
        patch.setattr(install_source.subprocess, "Popen", lambda argv, **_: started.append(argv))
        install_source.spawn_check()
    assert started
    argv = [*started[0][:-2], "--version"]  # the launch, without a network check
    subprocess.run(argv, cwd=repo, capture_output=True, timeout=60, env=env())
    assert not planted.exists(), started[0]


def test_hooks_from_before_the_safe_launch_ask_for_a_refresh(repo, capsys):
    assert main(["init"]) == 0
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    old = f"'{sys.executable}' -m cairnkit hook session-start --agent claude"
    settings.write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": old}]}]}})
    )
    project = find_project()
    refresh.record(project, None)  # the stamp says this version: only the text is old
    line = refresh.repo_line(project, None)
    assert line and "memory init --refresh" in line
    assert main(["init", "--refresh"]) == 0
    assert old not in settings.read_text()
    assert adapters.hook_command("session-start", "claude") in settings.read_text()
    assert refresh.repo_line(project, None) is None
    assert refresh.gone_pythons(project) == []


def test_an_old_git_hook_block_asks_for_a_refresh(repo, capsys):
    assert main(["init"]) == 0
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    project = find_project()
    for hook in ("pre-commit", "post-merge"):
        path = githook.hooks_dir(project) / hook
        text = path.read_text()
        assert " -P -m cairnkit" in text
        path.write_text(text.replace(" -P -m cairnkit", " -m cairnkit").replace(" -P -c ", " -c "))
    refresh.record(project, None)
    line = refresh.repo_line(project, None)
    assert line and "memory init --refresh" in line
    assert main(["init", "--refresh"]) == 0
    assert refresh.repo_line(project, None) is None
