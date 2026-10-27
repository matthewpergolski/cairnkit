"""The update lines in `memory status` and the session start.

One line when the installed tool is older than its source, and one line when
this repo's files come from an older tool. No test uses the network.
"""

from __future__ import annotations

import json

from conftest import git
from test_update import machine  # noqa: F401  (a fixture)

from cairnkit import install_source, instructions
from cairnkit.cli import main

OLD_BLOCK = f"{instructions.START}\nOld text.\n{instructions.END}\n"


def load_output(capsys) -> str:
    capsys.readouterr()
    assert main(["load"]) == 0
    return capsys.readouterr().out


def test_load_and_status_say_when_the_source_folder_is_newer(repo, machine, capsys):  # noqa: F811
    assert main(["init"]) == 0
    out = load_output(capsys)
    assert f"memory: a newer memory is at {machine.source} (0.1.0 -> 0.2.0" in out
    assert "`memory update` installs it." in out
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "memory 0.1.0" in out
    assert f"Source: {machine.source} (folder)" in out
    assert "a newer memory is at" in out


def test_status_shows_the_installed_git_ref(repo, machine, monkeypatch, capsys):  # noqa: F811
    """After an install, status names the short commit like uv's @hash."""
    from test_update import head

    assert main(["init"]) == 0
    assert main(["update"]) == 0
    monkeypatch.setattr(install_source, "current_version", lambda: "0.2.0")
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    short = head(machine.source)[:7]
    assert f"memory 0.2.0 @{short}" in out
    assert f"Source: {machine.source} (folder)" in out


def test_status_shows_commit_subjects_when_the_source_is_newer(
    repo, machine, monkeypatch, capsys
):  # noqa: F811
    from test_update import head

    assert main(["init"]) == 0
    monkeypatch.setenv("MEMORY_NOW", "2026-10-25T09:00:00+00:00")
    assert main(["update"]) == 0
    monkeypatch.setattr(install_source, "current_version", lambda: "0.2.0")
    git(machine.source, "commit", "-q", "--allow-empty", "-m", "Add the quiet hook.")
    git(machine.source, "commit", "-q", "--allow-empty", "-m", "Hide the alarm line.")
    # The post-update cache still says "not newer"; wait a day so status rechecks.
    monkeypatch.setenv("MEMORY_NOW", "2026-10-26T10:00:00+00:00")
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "a newer memory is at" in out
    assert "Add the quiet hook." in out
    assert "Hide the alarm line." in out
    assert head(machine.source)[:7] in out


def test_the_check_is_cached_for_a_day(repo, machine, monkeypatch, capsys):  # noqa: F811
    assert main(["init"]) == 0
    monkeypatch.setenv("MEMORY_NOW", "2026-10-25T09:00:00+00:00")
    assert "a newer memory" in load_output(capsys)
    (machine.source / "pyproject.toml").write_text(
        '[project]\nname = "cairnkit"\nversion = "0.1.0"\n'
    )
    git(machine.source, "commit", "-qam", "back to 0.1.0")
    monkeypatch.setenv("MEMORY_NOW", "2026-10-25T20:00:00+00:00")
    assert "a newer memory" in load_output(capsys)  # still the cached answer
    monkeypatch.setenv("MEMORY_NOW", "2026-10-26T10:00:00+00:00")
    assert "a newer memory" not in load_output(capsys)


def test_a_git_source_is_checked_in_the_background(repo, machine, monkeypatch, capsys):  # noqa: F811
    assert main(["init"]) == 0
    url = machine.source.as_uri()
    (machine.env / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "cairnkit", git = "{url}" }}]\n'
    )
    # An earlier `memory update` recorded an older commit.
    record = {"source": f"git+{url}", "commit": "0" * 40, "version": "0.1.0"}
    (machine.env / install_source.RECORD).write_text(json.dumps(record))
    started = []
    monkeypatch.setattr(install_source, "spawn_check", lambda: started.append(1))
    real_git = install_source.git

    def no_remote(args, timeout=3.0):
        assert args[0] != "ls-remote", "the session start must not wait for the network"
        return real_git(args, timeout)

    monkeypatch.setattr(install_source, "git", no_remote)
    assert "a newer memory" not in load_output(capsys)
    assert started == [1]
    load_output(capsys)
    assert started == [1]  # marked as started: not again in the next session
    # The background check finds a newer commit.
    monkeypatch.setattr(install_source, "git", real_git)
    assert main(["update", "--check"]) == 0
    assert "Update available" in capsys.readouterr().out
    monkeypatch.setattr(install_source, "git", no_remote)
    assert f"a newer memory is at {url}" in load_output(capsys)


def test_offline_says_nothing(repo, machine, monkeypatch, capsys):  # noqa: F811
    assert main(["init"]) == 0
    (machine.env / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "cairnkit", git = "https://example.invalid/m" }]\n'
    )
    monkeypatch.setattr(install_source, "git", lambda args, timeout=3.0: None)
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "newer" not in out
    assert "newer" not in load_output(capsys)


def test_no_line_without_a_known_source(repo, machine, capsys):  # noqa: F811
    (machine.env / "uv-receipt.toml").unlink()
    assert main(["init"]) == 0
    assert "newer memory" not in load_output(capsys)


def test_load_tells_the_agent_to_refresh_old_repo_files(repo, machine, monkeypatch, capsys):  # noqa: F811
    assert main(["init"]) == 0
    (repo / "AGENTS.md").write_text(OLD_BLOCK)
    out = load_output(capsys)
    assert "Run `memory init --refresh` now." in out
    assert main(["status"]) == 0
    assert "memory init --refresh" in capsys.readouterr().out
    assert main(["init", "--refresh"]) == 0
    assert "memory init --refresh" not in load_output(capsys)


def test_session_start_hook_shows_both_lines(repo, machine, monkeypatch, capsys):  # noqa: F811
    assert main(["init"]) == 0
    (repo / "AGENTS.md").write_text(OLD_BLOCK)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"session_id": "s1"})))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "claude"]) == 0
    out = capsys.readouterr().out
    assert "a newer memory is at" in out
    assert "memory init --refresh" in out
