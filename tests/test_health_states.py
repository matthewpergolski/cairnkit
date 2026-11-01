"""One state, one answer. Each row runs `memory status`, `memory check` and `memory load`."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from conftest import git, make_fact, write_facts

from cairnkit import githook
from cairnkit.cli import main
from cairnkit.migrate_refs import PENDING, TASK

SECRET = "password=hunter2hunter2"


def fresh_clone(repo: Path, tmp_path: Path, monkeypatch) -> None:
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(repo), str(clone))
    monkeypatch.chdir(clone)


def init(repo: Path) -> Path:
    assert main(["init", "--no-default-rules"]) == 0
    assert main(["hooks", "install"]) == 0
    return repo.parent / "proj.memory"


def healthy(repo: Path, tmp_path: Path, monkeypatch) -> None:
    init(repo)


def bad_line(repo: Path, tmp_path: Path, monkeypatch) -> None:
    with (init(repo) / "facts" / "main.jsonl").open("a") as fh:
        fh.write('{"typ\n')


def stored_secret(repo: Path, tmp_path: Path, monkeypatch) -> None:
    write_facts(init(repo), [make_fact("f-20261101-dead", f"prod {SECRET}")])


def notes_secret(repo: Path, tmp_path: Path, monkeypatch) -> None:
    (init(repo) / "notes" / "old.md").write_text(f"a line\n{SECRET}\n")


def old_hook_block(repo: Path, tmp_path: Path, monkeypatch) -> None:
    init(repo)
    hook = repo / ".git" / "hooks" / "post-commit"
    hook.write_text(
        "#!/bin/sh\n# >>> cairnkit >>>\n"
        f"'{sys.executable}' -m cairnkit hook post-commit || true\n# <<< cairnkit <<<\n"
    )
    hook.chmod(0o755)


def hooks_hidden(repo: Path, tmp_path: Path, monkeypatch) -> None:
    init(repo)
    (repo / ".githooks").mkdir()
    git(repo, "config", "core.hooksPath", ".githooks")


def python_gone(repo: Path, tmp_path: Path, monkeypatch) -> None:
    init(repo)
    for hook in (repo / ".git" / "hooks").iterdir():
        if hook.suffix != ".sample":
            hook.write_text(hook.read_text().replace(sys.executable, "/nonexistent/python"))


def moved_beside(repo: Path, tmp_path: Path, monkeypatch) -> None:
    shutil.move(str(init(repo)), str(tmp_path / "elsewhere"))


def moved_away(repo: Path, tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "far").mkdir()
    shutil.move(str(init(repo)), str(tmp_path / "far" / "away"))


def migration_open(repo: Path, tmp_path: Path, monkeypatch) -> None:
    (init(repo) / "proposals").mkdir(exist_ok=True)
    (repo.parent / "proj.memory" / TASK).write_text(f"{PENDING}: 2 item(s)\n\n- one\n- two\n")


def stale_atlas(repo: Path, tmp_path: Path, monkeypatch) -> None:
    init(repo)
    (repo / "docs" / "state").mkdir(parents=True)
    (repo / "docs" / "state" / "old.md").write_text("# old page\n")


def rename_break(repo: Path, tmp_path: Path, monkeypatch) -> None:
    """A move breaks only the absolute command of an earlier install. Today's command holds no path."""
    (repo / ".githooks").mkdir()
    git(repo, "config", "core.hooksPath", ".githooks")
    init(repo)
    for hook in githook.PERSONAL_HOOKS:
        old = repo / ".git" / githook.PRIVATE_DIR / hook
        git(repo, "config", "--local", f"hook.{githook.CONFIG_PREFIX}{hook}.command", str(old))
    moved = repo.rename(tmp_path / "renamed")
    monkeypatch.chdir(moved)


@dataclass(frozen=True)
class Row:
    setup: object
    answer: str  # the start of the one line that each command prints
    detail: str  # a phrase that names this state
    check: int  # the exit code of `memory check`
    strict: int  # the exit code of `memory check --strict`
    load_detail: bool = True  # text that comes from stored records stays out of the load
    stop_blocks: bool = False


OK = "memory check: ok"
NOT_LOADED = "memory: not loaded:"
ROWS = [
    Row(fresh_clone, f"{NOT_LOADED} no memory folder", "memory init", 0, 0),
    Row(healthy, OK, "", 0, 0),
    Row(bad_line, "memory check: 1 error(s)", "not valid JSON", 1, 1, False, True),
    Row(stored_secret, "memory check: 1 error(s)", "looks secret", 1, 1, True, True),
    Row(notes_secret, "memory check: 1 warning(s)", "notes/old.md:2", 0, 1, False, True),
    Row(old_hook_block, "memory check: 1 to do", "an old post-commit block", 0, 0),
    Row(hooks_hidden, "memory check: 1 to do", "core.hooksPath is .githooks", 0, 0),
    Row(python_gone, "memory check: 1 to do", "/nonexistent/python, which is gone", 0, 0),
    Row(moved_beside, f"{NOT_LOADED} This project's memory was at", "memory init --path", 1, 1),
    Row(moved_away, f"{NOT_LOADED} This project's memory was at", "memory init --path", 1, 1),
    Row(migration_open, "memory check: 1 to do", "2 item(s)", 0, 0),
    Row(stale_atlas, "memory check: 1 to do", "Docs atlas:", 0, 0),
    Row(rename_break, "memory check: 1 error(s)", "which is gone", 1, 1, False, True),
]


def run(capsys, *argv: str) -> tuple[int, list[str]]:
    capsys.readouterr()
    code = main(list(argv))
    return code, capsys.readouterr().out.splitlines()


def answer_of(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith(("memory check:", NOT_LOADED))]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.setup.__name__)
def test_every_command_gives_the_one_answer(row, repo, tmp_path, monkeypatch, capsys):
    row.setup(repo, tmp_path, monkeypatch)
    status_code, status = run(capsys, "status")
    check_code, check = run(capsys, "check")
    strict_code, _ = run(capsys, "check", "--strict")
    load_code, load = run(capsys, "load")

    assert (status_code, load_code) == (0, 0)
    assert (check_code, strict_code) == (row.check, row.strict)
    assert len(answer_of(check)) == 1, check
    answer = answer_of(check)[0]
    assert answer.startswith(row.answer)
    assert answer_of(status) == [answer]
    if row.answer == OK:
        assert answer_of(load) == [], "a healthy load spends no words on its health"
    else:
        assert answer_of(load) == [answer]
    assert "\n".join(check).count(row.detail)
    assert "\n".join(status).count(row.detail)
    if row.load_detail:
        assert "\n".join(load).count(row.detail)
    assert not any("Repo files: current" in line for line in status)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.setup.__name__)
def test_stop_blocks_only_on_what_strict_fails(row, repo, tmp_path, monkeypatch, capsys):
    row.setup(repo, tmp_path, monkeypatch)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"session_id": "s"})))
    code, out = run(capsys, "hook", "stop", "--agent", "claude")
    assert code == 0
    blocked = bool(out) and json.loads(out[0]).get("decision") == "block"
    assert blocked is row.stop_blocks


def _commit(folder: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "a commit after the move"],
        cwd=folder,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(not githook.git_runs_config_hooks(), reason="this git has no config hooks")
def test_session_start_heals_the_rename_break(repo, tmp_path, monkeypatch, capsys):
    rename_break(repo, tmp_path, monkeypatch)
    moved = tmp_path / "renamed"
    assert _commit(moved).returncode != 0, "the planted command must really break a commit"
    assert run(capsys, "hook", "session-start", "--agent", "generic")[0] == 0
    code, check = run(capsys, "check")
    assert code == 0
    assert not any("which is gone" in line for line in check)
    result = _commit(moved)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not githook.git_runs_config_hooks(), reason="this git has no config hooks")
def test_a_move_after_todays_install_is_healthy(repo, tmp_path, monkeypatch, capsys):
    (repo / ".githooks").mkdir()
    git(repo, "config", "core.hooksPath", ".githooks")
    init(repo)
    moved = repo.rename(tmp_path / "renamed")
    monkeypatch.chdir(moved)
    code, check = run(capsys, "check")
    assert code == 0
    assert answer_of(check)[0].startswith(OK)
    result = _commit(moved)
    assert result.returncode == 0, result.stderr


def test_a_problem_also_says_how_a_load_finds_the_fix(repo, tmp_path, monkeypatch, capsys):
    bad_line(repo, tmp_path, monkeypatch)
    _, load = run(capsys, "load")
    assert any("`memory check` lists each one" in line for line in load)
