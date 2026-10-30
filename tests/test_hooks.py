import io
import json
import subprocess

import pytest
from conftest import add_worktree, git, make_fact, write_facts

from cairnkit.cli import main


def run_hook(capsys, monkeypatch, event, agent, payload=None):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload or {})))
    capsys.readouterr()
    code = main(["hook", event, "--agent", agent])
    out = capsys.readouterr()
    return code, out.out, out.err


# --- check --strict -------------------------------------------------------


def test_strict_check_fails_on_warnings(mem, capsys):
    write_facts(mem, [make_fact("f-20261001-0001", "Fact.", writer="other")])
    assert main(["check"]) == 0
    assert main(["check", "--strict"]) == 1


# --- session start --------------------------------------------------------


def test_session_start_prints_load_for_claude(mem, capsys, monkeypatch):
    write_facts(mem, [make_fact("f-20261001-0001", "Deploys need a clean tree.")])
    code, out, _ = run_hook(
        capsys, monkeypatch, "session-start", "claude", {"session_id": "s1", "source": "startup"}
    )
    assert code == 0
    assert "Deploys need a clean tree." in out
    assert "memory add" in out
    assert (mem / ".sessions" / "s1.json").is_file()


def test_session_start_is_json_for_cursor(mem, capsys, monkeypatch):
    write_facts(mem, [make_fact("f-20261001-0001", "Deploys need a clean tree.")])
    code, out, _ = run_hook(
        capsys, monkeypatch, "session-start", "cursor", {"conversation_id": "c1"}
    )
    assert code == 0
    assert "Deploys need a clean tree." in json.loads(out)["additional_context"]


def test_session_start_without_memory_never_fails(repo, capsys, monkeypatch):
    code, out, err = run_hook(capsys, monkeypatch, "session-start", "cursor", {})
    assert code == 0
    assert out == "" and err == ""


# --- stop ---------------------------------------------------------------


def start(capsys, monkeypatch, agent="claude", sid="s1"):
    run_hook(
        capsys, monkeypatch, "session-start", agent, {"session_id": sid, "conversation_id": sid}
    )


def test_stop_is_quiet_when_nothing_changed(mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    code, out, _ = run_hook(capsys, monkeypatch, "stop", "claude", {"session_id": "s1"})
    assert code == 0 and "block" not in out


def test_stop_reminds_once_after_work_with_no_new_facts(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    (repo / "new.py").write_text("x = 1\n")
    code, out, _ = run_hook(capsys, monkeypatch, "stop", "claude", {"session_id": "s1"})
    assert code == 0
    data = json.loads(out)
    assert data["decision"] == "block" and "memory add" in data["reason"]
    # The agent was continued once; it must not loop.
    _, out, _ = run_hook(
        capsys, monkeypatch, "stop", "claude", {"session_id": "s1", "stop_hook_active": True}
    )
    assert "block" not in out
    # The same work does not cause a second reminder.
    _, out, _ = run_hook(capsys, monkeypatch, "stop", "claude", {"session_id": "s1"})
    assert "block" not in out


def test_stop_is_quiet_when_a_fact_was_written(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    (repo / "new.py").write_text("x = 1\n")
    main(["add", "New module.", "--area", "x", "--basis", "seen", "--source", "file:new.py"])
    _, out, _ = run_hook(capsys, monkeypatch, "stop", "claude", {"session_id": "s1"})
    assert "block" not in out


def test_stop_blocks_on_check_errors(mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    (mem / "facts" / "main.jsonl").write_text("{broken\n")
    _, out, _ = run_hook(capsys, monkeypatch, "stop", "claude", {"session_id": "s1"})
    data = json.loads(out)
    assert data["decision"] == "block" and "not valid JSON" in data["reason"]


def test_stop_formats_for_codex_cursor_and_generic(repo, mem, capsys, monkeypatch):
    for agent in ("codex", "cursor"):
        start(capsys, monkeypatch, agent, sid=agent)
    start(capsys, monkeypatch, "generic", sid="default")  # generic hooks send no payload
    _, out, _ = run_hook(capsys, monkeypatch, "stop", "codex", {"session_id": "codex"})
    assert json.loads(out) == {}
    (repo / "new.py").write_text("x = 1\n")
    _, out, _ = run_hook(capsys, monkeypatch, "stop", "codex", {"session_id": "codex"})
    assert json.loads(out)["decision"] == "block"
    _, out, _ = run_hook(
        capsys, monkeypatch, "stop", "cursor", {"conversation_id": "cursor", "loop_count": 0}
    )
    assert "memory add" in json.loads(out)["followup_message"]
    code, out, err = run_hook(capsys, monkeypatch, "stop", "generic", {})
    assert code == 1 and "memory add" in err


def test_cursor_stop_does_not_loop(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch, "cursor", sid="c1")
    (repo / "new.py").write_text("x = 1\n")
    _, out, _ = run_hook(
        capsys, monkeypatch, "stop", "cursor", {"conversation_id": "c1", "loop_count": 1}
    )
    assert json.loads(out) == {}


# --- install -------------------------------------------------------------


def install(capsys, *args):
    capsys.readouterr()
    code = main(["hooks", "install", *args])
    return code, capsys.readouterr().out


def our_commands(groups):
    return [
        h["command"] for g in groups for h in g.get("hooks", [g]) if "cairnkit hook" in h["command"]
    ]


def test_install_claude_merges_and_is_idempotent(repo, mem, capsys):
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    other = {"type": "command", "command": "echo other"}
    settings.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [other]}]}}))
    assert install(capsys, "--agent", "claude")[0] == 0
    assert install(capsys, "--agent", "claude")[0] == 0
    data = json.loads(settings.read_text())
    assert data["model"] == "x"
    assert other in [h for g in data["hooks"]["Stop"] for h in g["hooks"]]
    assert len(our_commands(data["hooks"]["Stop"])) == 1
    assert len(our_commands(data["hooks"]["SessionStart"])) == 1
    assert "--agent claude" in our_commands(data["hooks"]["SessionStart"])[0]
    git(repo, "check-ignore", "-q", ".claude/settings.local.json")
    assert git(repo, "status", "--porcelain") == ""


def test_install_codex_and_cursor_formats(repo, mem, capsys):
    assert install(capsys, "--agent", "codex")[0] == 0
    codex = json.loads((repo / ".codex" / "hooks.json").read_text())
    assert codex["hooks"]["SessionStart"][0]["matcher"] == "startup|resume"
    assert len(our_commands(codex["hooks"]["Stop"])) == 1
    assert install(capsys, "--agent", "cursor")[0] == 0
    cursor = json.loads((repo / ".cursor" / "hooks.json").read_text())
    assert cursor["version"] == 1
    assert "--agent cursor" in cursor["hooks"]["sessionStart"][0]["command"]
    assert cursor["hooks"]["stop"][0]["loop_limit"] == 1
    assert git(repo, "status", "--porcelain") == ""


def test_install_into_every_worktree(repo, mem, capsys):
    wt = add_worktree(repo, "feat")
    assert install(capsys, "--agent", "claude")[0] == 0
    assert (wt / ".claude" / "settings.local.json").is_file()


def test_bad_json_is_never_clobbered(repo, mem, capsys):
    path = repo / ".cursor" / "hooks.json"
    path.parent.mkdir()
    path.write_text("{not json")
    code, _ = install(capsys, "--agent", "cursor")
    assert code == 1
    assert path.read_text() == "{not json"


def test_tracked_config_is_left_alone(repo, mem, capsys):
    path = repo / ".cursor" / "hooks.json"
    path.parent.mkdir()
    path.write_text('{"version": 1, "hooks": {}}\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "team hooks")
    code, out = install(capsys, "--agent", "cursor")
    assert code == 0
    assert "tracked" in out
    assert path.read_text() == '{"version": 1, "hooks": {}}\n'


def test_generic_prints_commands_and_writes_no_agent_file(repo, mem, capsys):
    code, out = install(capsys, "--agent", "generic")
    assert code == 0
    assert "hook session-start" in out and "hook stop" in out
    for folder in (".claude", ".codex", ".cursor"):
        assert not (repo / folder).exists()


def test_auto_detects_agent_folders(repo, mem, capsys, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    (repo / ".claude").mkdir()
    code, _ = install(capsys)
    assert code == 0
    assert (repo / ".claude" / "settings.local.json").is_file()
    assert not (repo / ".cursor").exists()


def test_dry_run_writes_nothing(repo, mem, capsys):
    code, out = install(capsys, "--agent", "claude", "--dry-run")
    assert code == 0 and "would" in out
    assert not (repo / ".claude").exists()
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()


def test_uninstall_removes_only_our_entries(repo, mem, capsys):
    settings = repo / ".claude" / "settings.local.json"
    settings.parent.mkdir()
    other = {"type": "command", "command": "echo other"}
    settings.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [other]}]}}))
    install(capsys, "--agent", "claude")
    assert main(["hooks", "uninstall"]) == 0
    data = json.loads(settings.read_text())
    assert data == {"hooks": {"Stop": [{"hooks": [other]}]}}
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()


# --- git pre-commit --------------------------------------------------------


def commit(repo):
    return subprocess.run(
        ["git", "commit", "-q", "-m", "x"], cwd=repo, capture_output=True, text=True
    )


def test_pre_commit_refuses_the_link(repo, mem, capsys):
    install(capsys, "--agent", "generic")
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.is_file() and hook.stat().st_mode & 0o111
    git(repo, "add", "-f", "memory-bank")
    result = commit(repo)
    assert result.returncode != 0
    assert "memory-bank" in result.stderr
    git(repo, "reset", "-q")
    (repo / "ok.txt").write_text("ok\n")
    git(repo, "add", "ok.txt")
    assert commit(repo).returncode == 0


def test_pre_commit_keeps_a_foreign_hook(repo, mem, capsys):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho team-check\nexit 0\n")
    hook.chmod(0o755)
    install(capsys, "--agent", "generic")
    install(capsys, "--agent", "generic")
    text = hook.read_text()
    assert text.startswith("#!/bin/sh\n")
    assert "echo team-check" in text
    assert text.count(">>> cairnkit >>>") == 1
    assert text.index("cairnkit") < text.index("team-check")
    main(["hooks", "uninstall"])
    assert hook.read_text() == "#!/bin/sh\necho team-check\nexit 0\n"


def test_hooks_path_inside_repo_is_left_alone(repo, mem, capsys):
    (repo / ".githooks").mkdir()
    git(repo, "config", "core.hooksPath", ".githooks")
    code, out = install(capsys, "--agent", "generic")
    assert code == 0
    assert "by hand" in out
    assert not (repo / ".githooks" / "pre-commit").exists()


@pytest.mark.parametrize("path", ["memory-bank", ".memory-path"])
def test_pre_commit_command_names_the_bad_path(repo, mem, capsys, path):
    if path == ".memory-path":
        (repo / ".memory-path").write_text("../proj.memory\n")
    git(repo, "add", "-f", path)
    capsys.readouterr()
    assert main(["hook", "pre-commit"]) == 1
    assert path in capsys.readouterr().err
