"""Pi, OpenCode and Grok Build get the memory with no tracked file and no manual step."""

from __future__ import annotations

import io
import json

import pytest
from conftest import git

from cairnkit import adapters, install_source
from cairnkit.cli import main
from cairnkit.install_source import Source


def _install(repo, *names):
    for name in names:
        assert main(["hooks", "install", "--agent", name]) == 0


def test_each_adapter_writes_an_untracked_file(repo, mem):
    _install(repo, "pi", "opencode", "grok")
    assert "cairnkit" in (repo / ".pi" / "extensions" / "cairnkit.ts").read_text()
    assert "session.created" in (repo / ".opencode" / "plugins" / "cairnkit.js").read_text()
    grok = json.loads((repo / ".grok" / "hooks" / "cairnkit.json").read_text())
    assert {"SessionStart", "Stop", "PostToolUse", "PostToolUseFailure"} <= set(grok["hooks"])
    assert git(repo, "status", "--porcelain") == ""


def test_a_second_install_changes_nothing(repo, mem, capsys):
    _install(repo, "pi")
    capsys.readouterr()
    _install(repo, "pi")
    assert "Already installed" in capsys.readouterr().out


def test_uninstall_removes_each_generated_file(repo, mem):
    _install(repo, "pi", "opencode", "grok")
    assert main(["hooks", "uninstall"]) == 0
    assert not (repo / ".pi" / "extensions" / "cairnkit.ts").exists()
    assert not (repo / ".opencode" / "plugins" / "cairnkit.js").exists()
    assert not (repo / ".grok" / "hooks" / "cairnkit.json").exists()


def test_a_foreign_file_is_kept(repo, mem, capsys):
    path = repo / ".pi" / "extensions" / "cairnkit.ts"
    path.parent.mkdir(parents=True)
    path.write_text("mine")
    _install(repo, "pi")
    assert path.read_text() == "mine"
    assert "not ours" in capsys.readouterr().out


def test_refresh_rewrites_a_generated_file(repo, mem):
    _install(repo, "pi")
    path = repo / ".pi" / "extensions" / "cairnkit.ts"
    path.write_text(path.read_text() + "// old\n")
    assert main(["init", "--refresh"]) == 0
    assert "// old" not in path.read_text()


def test_grok_is_not_connected_twice(repo, mem, monkeypatch):
    names = {"grok", "claude"}
    monkeypatch.setattr(adapters.shutil, "which", lambda name: name if name in names else None)
    project = __import__("cairnkit.paths", fromlist=["find_project"]).find_project()
    assert adapters.detect(project) == ["claude"]
    names.discard("claude")
    assert adapters.detect(project) == ["grok"]


def test_grok_gets_the_load_at_the_first_tool_result(repo, mem, capsys, monkeypatch):
    add = ["--area", "x", "--basis", "seen", "--source", "session:1"]
    assert main(["add", "A stored fact.", *add]) == 0
    monkeypatch.setenv("GROK_HOOK_EVENT", "x")

    def hook(event, payload):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        capsys.readouterr()
        assert main(["hook", event, "--agent", "claude"]) == 0
        return capsys.readouterr().out

    assert "systemMessage" in hook("session-start", {"session_id": "s"})
    first = {"session_id": "s", "hook_event_name": "PostToolUse", "tool_name": "Read"}
    out = json.loads(hook("after-shell", first))
    assert "A stored fact." in out["hookSpecificOutput"]["additionalContext"]
    assert hook("after-shell", first) == ""


@pytest.mark.parametrize("agent", ["pi", "opencode"])
def test_a_text_adapter_reads_stop_on_stdout_with_exit_zero(repo, mem, capsys, monkeypatch, agent):
    def hook(event):
        monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "s"}'))
        capsys.readouterr()
        code = main(["hook", event, "--agent", agent])
        return code, capsys.readouterr().out

    hook("session-start")
    (repo / "new.py").write_text("x\n")
    code, out = hook("stop")
    assert code == 0
    assert "new.py" in out


def _ls_remote(calls):
    def fake(args, timeout=3.0):
        calls.append(args)
        if "--tags" in args:
            return "aaa\trefs/tags/9.9.9"
        return "bbb\trefs/heads/dev"

    return fake


def test_stable_takes_the_highest_tag(monkeypatch):
    monkeypatch.setattr(install_source, "git", _ls_remote([]))
    assert install_source.latest(Source("https://x/y.git", "git")).commit == "aaa"


def test_dev_channel_takes_the_dev_branch(monkeypatch):
    monkeypatch.setattr(install_source, "git", _ls_remote([]))
    install_source.set_channel("dev")
    assert install_source.channel() == "dev"
    assert install_source.latest(Source("https://x/y.git", "git")).commit == "bbb"


def test_an_install_pinned_to_dev_follows_dev(monkeypatch):
    monkeypatch.setattr(install_source, "git", _ls_remote([]))
    source = install_source.parse("git+https://x/y.git@dev")
    assert install_source.channel(source) == "dev"
    assert install_source.latest(source).commit == "bbb"


def test_a_saved_channel_wins_over_a_pin():
    install_source.set_channel("stable")
    assert install_source.channel(install_source.parse("git+https://x/y.git@dev")) == "stable"
