"""A dev build and a prod build of one version can be told apart. Repo files tell the truth."""

from __future__ import annotations

import json
import subprocess

import pytest
from conftest import git, read_jsonl

from cairnkit import githook, install_source, instructions
from cairnkit.cli import main
from cairnkit.update import _verify

COMMIT = "85b0cd0" + "a" * 33
URL = "https://example.invalid/cairnkit"


def version_output(capsys) -> str:
    capsys.readouterr()
    with pytest.raises(SystemExit):
        main(["--version"])
    return capsys.readouterr().out.strip()


def status_output(capsys) -> list[str]:
    capsys.readouterr()
    assert main(["status"]) == 0
    return capsys.readouterr().out.splitlines()


def tool_env(tmp_path, monkeypatch, receipt: str | None = None, record: dict | None = None):
    env = tmp_path / "tools" / "cairnkit"
    env.mkdir(parents=True)
    if receipt:
        (env / "uv-receipt.toml").write_text(
            f'[tool]\nrequirements = [{{ name = "cairnkit", {receipt} }}]\n'
        )
    if record:
        (env / install_source.RECORD).write_text(json.dumps(record))
    monkeypatch.setattr(install_source, "tool_env", lambda: env)
    monkeypatch.setattr(install_source, "current_version", lambda: "0.3.1")
    return env


def direct_url(monkeypatch, data: dict | None) -> None:
    monkeypatch.setattr(install_source, "_direct_url", lambda: data)


def checkout(tmp_path, branch: str):
    folder = tmp_path / "checkout"
    folder.mkdir()
    git(folder, "init", "-q", "-b", branch)
    git(
        folder,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@e.invalid",
        "commit",
        "-qm",
        "x",
        "--allow-empty",
    )
    return folder, git(folder, "rev-parse", "HEAD").strip()


# --- the name of the build ------------------------------------------------------------


def test_a_tag_install_keeps_the_plain_line_that_old_tools_verify(tmp_path, monkeypatch, capsys):
    tool_env(tmp_path, monkeypatch, f'git = "{URL}@v0.3.1"')
    direct_url(
        monkeypatch,
        {
            "url": URL,
            "vcs_info": {"vcs": "git", "commit_id": COMMIT, "requested_revision": "v0.3.1"},
        },
    )
    assert version_output(capsys) == "memory 0.3.1"


def test_a_dev_channel_install_names_channel_and_commit(tmp_path, monkeypatch, capsys):
    tool_env(tmp_path, monkeypatch, f'git = "{URL}@dev"')
    direct_url(
        monkeypatch,
        {"url": URL, "vcs_info": {"vcs": "git", "commit_id": COMMIT, "requested_revision": "dev"}},
    )
    assert version_output(capsys) == "memory 0.3.1 (dev @85b0cd0)"


def test_the_saved_dev_channel_with_a_record_names_the_commit(tmp_path, monkeypatch, capsys):
    record = {"source": f"git+{URL}", "commit": COMMIT, "version": "0.3.1"}
    tool_env(tmp_path, monkeypatch, record=record)
    direct_url(monkeypatch, None)
    install_source.set_channel("dev")
    assert version_output(capsys) == "memory 0.3.1 (dev @85b0cd0)"


def test_an_editable_checkout_on_dev_names_channel_and_commit(tmp_path, monkeypatch, capsys):
    folder, head = checkout(tmp_path, "dev")
    tool_env(tmp_path, monkeypatch)
    direct_url(monkeypatch, {"url": f"file://{folder}", "dir_info": {"editable": True}})
    assert version_output(capsys) == f"memory 0.3.1 (dev @{head[:7]})"


def test_an_editable_checkout_on_a_branch_names_the_branch(tmp_path, monkeypatch, capsys):
    folder, head = checkout(tmp_path, "feature")
    tool_env(tmp_path, monkeypatch)
    direct_url(monkeypatch, {"url": f"file://{folder}", "dir_info": {"editable": True}})
    assert version_output(capsys) == f"memory 0.3.1 (checkout feature @{head[:7]})"


def test_a_build_from_a_folder_names_the_folder_and_the_commit(tmp_path, monkeypatch, capsys):
    source = tmp_path / "src"
    source.mkdir()
    record = {"source": str(source), "commit": COMMIT, "version": "0.3.1"}
    tool_env(tmp_path, monkeypatch, f'directory = "{source}"', record)
    direct_url(monkeypatch, None)
    assert version_output(capsys) == "memory 0.3.1 (folder @85b0cd0)"


def test_an_unknown_install_stays_plain(tmp_path, monkeypatch, capsys):
    tool_env(tmp_path, monkeypatch)
    direct_url(monkeypatch, None)
    assert version_output(capsys) == "memory 0.3.1"


def test_a_broken_direct_url_file_stays_plain(tmp_path, monkeypatch, capsys):
    tool_env(tmp_path, monkeypatch)
    direct_url(monkeypatch, {"url": 7, "vcs_info": "nonsense"})
    assert version_output(capsys) == "memory 0.3.1"


def test_status_names_the_channel_and_commit_of_a_checkout(repo, tmp_path, monkeypatch, capsys):
    folder, head = checkout(tmp_path, "dev")
    tool_env(tmp_path, monkeypatch)
    direct_url(monkeypatch, {"url": f"file://{folder}", "dir_info": {"editable": True}})
    assert main(["init"]) == 0
    lines = status_output(capsys)
    assert lines[0] == f"memory 0.3.1 @{head[:7]}"
    assert "Channel: dev" in lines


def test_status_shows_the_commit_of_a_tag_install(repo, tmp_path, monkeypatch, capsys):
    tool_env(tmp_path, monkeypatch, f'git = "{URL}@v0.3.1"')
    direct_url(monkeypatch, {"url": URL, "vcs_info": {"vcs": "git", "commit_id": COMMIT}})
    monkeypatch.setattr(install_source, "spawn_check", lambda: None)
    monkeypatch.setattr(install_source, "git", lambda args, timeout=3.0: None)
    assert main(["init"]) == 0
    lines = status_output(capsys)
    assert lines[0] == "memory 0.3.1 @85b0cd0"
    assert "Channel: stable" in lines


def test_the_check_compares_the_commit_of_a_dev_channel_install(tmp_path, monkeypatch):
    tool_env(tmp_path, monkeypatch, f'git = "{URL}@dev"')
    direct_url(
        monkeypatch,
        {"url": URL, "vcs_info": {"vcs": "git", "commit_id": COMMIT, "requested_revision": "dev"}},
    )
    assert install_source.installed(None)[1] == COMMIT


def test_a_stable_install_at_another_commit_is_not_offered_the_older_tag(tmp_path, monkeypatch):
    tool_env(tmp_path, monkeypatch, f'git = "{URL}"')
    direct_url(monkeypatch, {"url": URL, "vcs_info": {"vcs": "git", "commit_id": COMMIT}})
    assert install_source.installed(None)[1] is None


def test_the_check_from_the_running_checkout_knows_its_own_commit(tmp_path, monkeypatch):
    folder, head = checkout(tmp_path, "dev")
    tool_env(tmp_path, monkeypatch)
    direct_url(monkeypatch, {"url": f"file://{folder}", "dir_info": {"editable": True}})
    assert install_source.installed(str(folder))[1] == head


def test_verify_reads_the_version_word_of_a_dev_build(tmp_path, monkeypatch):
    bar = type("Bar", (), {"start": lambda *a: None, "done": lambda *a: None})()
    script = tmp_path / "memory"
    script.write_text('#!/bin/sh\necho "memory 0.3.2 (dev @85b0cd0)"\n')
    script.chmod(0o755)
    monkeypatch.setattr(install_source, "entrypoint", lambda: str(script))
    found = install_source.Latest(COMMIT, "0.3.2")
    source = install_source.parse(URL)
    assert _verify(bar, source, found) == "0.3.2"


def test_the_version_needs_no_git_for_a_plain_install(tmp_path, monkeypatch, capsys):
    tool_env(tmp_path, monkeypatch)
    direct_url(monkeypatch, None)

    def no_process(*args, **kwargs):
        raise AssertionError("a plain version needs no process")

    monkeypatch.setattr(subprocess, "run", no_process)
    assert version_output(capsys) == "memory 0.3.1"


ANSWER_OK = "memory check: ok"


def repo_lines(lines: list[str]) -> list[str]:
    """The status lines that ask for a refresh of the repo files."""
    return [line for line in lines if "memory init --refresh" in line]


# --- `memory check: ok` is true -------------------------------------------------------


def old_block(repo, hook: str = "post-commit", marks=None) -> None:
    path = repo / ".git" / "hooks" / hook
    start, end = marks or githook.PAIRS[0]
    path.write_text(f"#!/bin/sh\necho mine\n{start}\nmemory hook post-commit\n{end}\n")
    path.chmod(0o755)


def plain_install(tmp_path, monkeypatch):
    tool_env(tmp_path, monkeypatch)
    direct_url(monkeypatch, None)


def test_a_leftover_post_commit_block_is_not_current(repo, tmp_path, monkeypatch, capsys):
    plain_install(tmp_path, monkeypatch)
    assert main(["init"]) == 0
    old_block(repo)
    lines = status_output(capsys)
    assert not any(ANSWER_OK in line for line in lines)
    assert any("post-commit" in line and "memory init --refresh" in line for line in lines)


def test_the_load_names_the_leftover_block(repo, tmp_path, monkeypatch, capsys):
    plain_install(tmp_path, monkeypatch)
    assert main(["init"]) == 0
    old_block(repo)
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "post-commit" in capsys.readouterr().out


def test_refresh_removes_the_block_and_keeps_the_owners_lines(repo, tmp_path, monkeypatch, capsys):
    plain_install(tmp_path, monkeypatch)
    assert main(["init"]) == 0
    old_block(repo)
    assert main(["init", "--refresh"]) == 0
    hook = repo / ".git" / "hooks" / "post-commit"
    assert not githook.holds_block(hook.read_text())
    assert "echo mine" in hook.read_text()
    assert not repo_lines(status_output(capsys))


def test_a_hook_with_the_markers_from_before_the_rename_is_not_current(
    repo, tmp_path, monkeypatch, capsys
):
    plain_install(tmp_path, monkeypatch)
    assert main(["init"]) == 0
    old_block(repo, "pre-push", githook.PAIRS[1])
    assert repo_lines(status_output(capsys))
    assert main(["init", "--refresh"]) == 0
    text = (repo / ".git" / "hooks" / "pre-push").read_text()
    assert githook.PAIRS[1][0] not in text
    assert not repo_lines(status_output(capsys))


def test_a_fresh_init_is_current(repo, tmp_path, monkeypatch, capsys):
    plain_install(tmp_path, monkeypatch)
    assert main(["init"]) == 0
    assert not repo_lines(status_output(capsys))


def _mined_fact(mem) -> str:
    text = "This package is the one place that reads the cookie and the code on a link."
    fact = {
        "type": "fact",
        "id": "f-20261030-c95e",
        "kind": "trap",
        "text": text,
        "area": "general",
        "happened_at": "2026-10-30",
        "learned_at": "2026-10-30T10:00:00+00:00",
        "source": "commit:abc1234",
        "basis": "guess",
        "status": "active",
        "scope": "long",
        "writer": "main",
    }
    (mem / "facts" / "main.jsonl").write_text(json.dumps(fact) + "\n")
    candidate = {
        "type": "candidate",
        "id": "c-1",
        "kind": "trap",
        "text": text,
        "source": "commit:abc1234",
        "area": "general",
    }
    # The hook wrote both in one run of tag v0.3.1. That time is the proof that the gate wrote it.
    candidate["created_at"] = "2026-10-01T12:00:00+00:00"
    decision = {
        "type": "decision",
        "id": "c-1",
        "status": "accepted",
        "fact_id": fact["id"],
        "at": "2026-10-01T12:00:00+00:00",
    }
    (mem / "proposals").mkdir(exist_ok=True)
    (mem / "proposals" / "auto-candidates.jsonl").write_text(
        json.dumps(candidate) + "\n" + json.dumps(decision) + "\n"
    )
    return text


def test_refresh_ends_the_mined_facts_with_no_session_start(
    mem, repo, tmp_path, monkeypatch, capsys
):
    plain_install(tmp_path, monkeypatch)
    text = _mined_fact(mem)
    assert "memory init --refresh" in "\n".join(status_output(capsys))
    capsys.readouterr()
    assert main(["load"]) == 0
    loaded = capsys.readouterr().out
    assert text in loaded
    assert "memory init --refresh" in loaded
    assert main(["init", "--refresh"]) == 0
    capsys.readouterr()
    assert main(["load"]) == 0
    assert text not in capsys.readouterr().out
    assert any(r.get("status") == "expired" for r in read_jsonl(mem / "facts" / "auto-tidy.jsonl"))


def test_a_refresh_dry_run_ends_no_mined_fact(mem, repo, tmp_path, monkeypatch, capsys):
    plain_install(tmp_path, monkeypatch)
    text = _mined_fact(mem)
    assert main(["init", "--refresh", "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["load"]) == 0
    assert text in capsys.readouterr().out


# --- the subagent line ----------------------------------------------------------------


def test_the_instructions_say_how_a_subagent_gets_memory():
    lines = [line for line in instructions.text().splitlines() if "ubagent" in line]
    assert lines, "the rules must mention a subagent"
    assert any("memory load" in line for line in lines)
    assert instructions.text().lower().count("subagent") <= 2
