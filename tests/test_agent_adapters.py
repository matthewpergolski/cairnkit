"""Pi, OpenCode and Grok Build get the memory with no tracked file and no manual step."""

from __future__ import annotations

import io
import json
import shutil
import subprocess

import pytest
from conftest import git

from cairnkit import adapters, install_source
from cairnkit.cli import main
from cairnkit.install_source import Source
from cairnkit.paths import find_project


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


def _grok_hook(capsys, monkeypatch, event, payload):
    monkeypatch.setenv("GROK_HOOK_EVENT", "x")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    capsys.readouterr()
    assert main(["hook", event, "--agent", "grok"]) == 0
    return capsys.readouterr().out


def test_grok_with_no_tool_call_gets_the_load_at_stop_once(repo, mem, capsys, monkeypatch):
    add = ["--area", "x", "--basis", "seen", "--source", "session:1"]
    assert main(["add", "A stored fact.", *add]) == 0
    session = {"session_id": "s"}
    _grok_hook(capsys, monkeypatch, "session-start", session)
    out = json.loads(_grok_hook(capsys, monkeypatch, "stop", session))
    assert out["decision"] == "block"
    assert "A stored fact." in out["reason"]
    assert _grok_hook(capsys, monkeypatch, "stop", session) == ""
    first = {"session_id": "s", "hook_event_name": "PostToolUse", "tool_name": "Read"}
    assert _grok_hook(capsys, monkeypatch, "after-shell", first) == ""


def test_a_continued_grok_stop_keeps_the_held_load(repo, mem, capsys, monkeypatch):
    add = ["--area", "x", "--basis", "seen", "--source", "session:1"]
    assert main(["add", "A stored fact.", *add]) == 0
    _grok_hook(capsys, monkeypatch, "session-start", {"session_id": "s"})
    active = {"session_id": "s", "stop_hook_active": True}
    assert _grok_hook(capsys, monkeypatch, "stop", active) == ""
    assert "A stored fact." in _grok_hook(capsys, monkeypatch, "stop", {"session_id": "s"})


def test_grok_prompt_news_waits_for_a_channel_that_reaches_the_model(
    repo, mem, capsys, monkeypatch
):
    session = {"session_id": "s"}
    _grok_hook(capsys, monkeypatch, "session-start", session)
    _grok_hook(capsys, monkeypatch, "stop", session)
    monkeypatch.setenv("MEMORY_WRITER", "other")
    assert main(["add", "Learned elsewhere.", "--basis", "seen", "--source", "session:1"]) == 0
    monkeypatch.delenv("MEMORY_WRITER")
    assert _grok_hook(capsys, monkeypatch, "prompt", session) == ""
    assert "Learned elsewhere." in _grok_hook(capsys, monkeypatch, "stop", session)


def test_the_generic_help_names_what_stop_says_now():
    text = adapters.generic_help()
    assert "run `memory check`" not in text
    assert "`memory search WORDS`" in text


@pytest.mark.parametrize(
    ("name", "events"),
    [
        ("claude", ("session-start", "stop", "after-shell", "prompt", "subagent-start")),
        ("cursor", ("session-start", "stop", "after-shell", "pre-compact")),
    ],
)
def test_the_tracked_file_message_lists_each_command_and_no_team(repo, mem, name, events):
    rel = adapters.ADAPTERS[name].rel
    path = repo / rel
    path.parent.mkdir(exist_ok=True)
    path.write_text("{}\n")
    git(repo, "add", "-f", rel)
    step = adapters.apply(find_project(), name, True, True)[0]
    assert "tracked by git" in step
    assert "team" not in step
    assert all(f"hook {event} --agent {name}" in step for event in events)


PI_DRIVER = """
import { readFileSync, writeFileSync } from "node:fs";
import extension from "./cairnkit.ts";

const handlers = {};
const sent = [];
extension({
  on: (name, handler) => (handlers[name] = handler),
  sendMessage: (message, options) => sent.push({ content: message.content, options }),
});
let idle = false;
const ctx = {
  hasUI: process.argv[2] === "ui",
  isIdle: () => idle,
  hasPendingMessages: () => false,
  sessionManager: {
    getSessionFile: () => "s",
    getEntries: () => (process.argv[3] === "resume" ? [{ type: "message" }] : []),
  },
};
const wait = (ms) => new Promise((done) => setTimeout(done, ms));
const told = () => "reminded" in JSON.parse(readFileSync("../proj.memory/.sessions/s.json"));
const assistant = (stopReason) => ({ messages: [{ role: "assistant", stopReason }] });
const report = {};

await handlers.session_start({ reason: "startup" }, ctx);
report.first = (await handlers.before_agent_start({}, ctx))?.message?.content ?? "";
writeFileSync("new.py", "x = 1\\n");

await handlers.agent_end(assistant("aborted"), ctx);
idle = true;
await wait(400);
report.aborted = { sent: sent.length, told: told() };
idle = false;

await handlers.agent_end(assistant("stop"), ctx);
await wait(200);
report.busy = { sent: sent.length, told: told() };
idle = true;
for (let i = 0; ctx.hasUI && i < 200 && sent.length === 0; i++) await wait(50);
await wait(200);
report.idle = { told: told(), sent: sent.map((item) => item.options) };
report.text = sent.map((item) => item.content).join("");
if (process.argv[3] === "first-run") {
  console.log(JSON.stringify(report));
  process.exit(0);
}

await handlers.agent_end(assistant("stop"), ctx);
await wait(400);
report.again = sent.length;

report.next = (await handlers.before_agent_start({}, ctx))?.message?.content ?? "";
console.log(JSON.stringify(report));
process.exit(0);
"""


def _drive_pi(repo, *argv):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    assert main(["hooks", "install", "--agent", "pi"]) == 0
    folder = repo / ".pi" / "extensions"
    (folder / "driver.mjs").write_text(PI_DRIVER)
    done = subprocess.run(
        [node, "--experimental-strip-types", "--no-warnings", str(folder / "driver.mjs"), *argv],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if "ERR_UNKNOWN_FILE_EXTENSION" in done.stderr or "bad option" in done.stderr:
        pytest.skip("this node cannot load TypeScript")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_pi_with_a_ui_tells_stop_only_when_a_turn_can_start(repo, mem):
    report = _drive_pi(repo, "ui")
    assert report["aborted"] == {"sent": 0, "told": False}
    assert report["busy"] == {"sent": 0, "told": False}
    assert report["idle"] == {"told": True, "sent": [{"triggerTurn": True}]}
    assert "new.py" in report["text"]
    assert report["again"] == 1
    assert "new.py" not in report["next"]


def test_pi_in_print_mode_holds_stop_for_the_next_prompt(repo, mem):
    report = _drive_pi(repo, "print")
    assert report["idle"] == {"told": False, "sent": []}
    assert report["again"] == 0
    assert "new.py" in report["next"]


def test_pi_in_print_mode_delivers_a_held_stop_after_a_continued_run(repo, mem):
    assert "new.py" not in _drive_pi(repo, "print", "first-run")["first"]
    assert "new.py" in _drive_pi(repo, "print", "resume")["first"]
