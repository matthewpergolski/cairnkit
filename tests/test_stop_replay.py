"""Replay 20 ordinary turns through the real hooks. A block costs the owner a turn."""

import io
import json
import subprocess

import pytest
from conftest import git

from cairnkit.cli import main

AGENTS = ("claude", "codex", "cursor", "grok", "pi", "opencode")
REMINDER = "No fact was written for this work"
LOST = "was here when this session started"


def edit(path, text):
    return f"mkdir -p $(dirname {path}); echo '{text}' >> {path}"


def commit(message):
    return f"git add -A; git commit -qm '{message}'"


PLAIN = [
    ("add a retry helper to src/net.py", [edit("src/net.py", "def retry(): pass")], [("pytest", 1)]),
    (
        "write a test for the retry helper",
        [edit("tests/test_net.py", "def test_r(): pass")],
        [("pytest", 1)],
    ),
    ("commit that", [commit("add retry")], [("git commit", 1)]),
    ("now add a timeout argument", [edit("src/net.py", "# timeout arg")], [("pytest", 1)]),
    ("explain what the retry loop does", [], []),
    ("add logging at debug level", [edit("src/net.py", "# logging")], [("pytest", 1)]),
    ("run the tests", [], [("pytest", 1)]),
    ("commit", [commit("timeout and logging")], [("git commit", 1)]),
    ("what does the config loader read", [], []),
    ("add a config key for the base url", [edit("src/config.py", "BASE=1")], [("pytest", 1)]),
    ("use it in the client", [edit("src/client.py", "from config import BASE")], [("pytest", 1)]),
    ("update the README section on config", [edit("README.md", "config docs")], []),
    (
        "commit and open a branch for the next part",
        [f"{commit('config')}; git switch -qc next"],
        [("git commit", 1)],
    ),
    ("add a small cache to the client", [edit("src/client.py", "cache={}")], [("pytest", 1)]),
    ("add a test for the cache", [edit("tests/test_client.py", "def test_c(): pass")], [("pytest", 1)]),
    ("looks good, thanks. how big is the diff", [], [("git diff --stat", 1)]),
    ("commit", [commit("cache")], [("git commit", 1)]),
    ("format the code", [edit("src/client.py", "# fmt")], [("ruff format", 1)]),
    ("commit that too", [commit("fmt")], [("git commit", 1)]),
    ("summarize what we did today", [], []),
]
MIXED = list(PLAIN)
MIXED[3] = (
    "why did you pick a fixed delay here? add a timeout argument",
    [edit("src/net.py", "# timeout arg")],
    [("pytest", 0), ("pytest", 0), ("pytest", 1)],
)
MIXED[6] = (
    "run the tests, I think it is not what the spec says for backoff",
    [edit("src/net.py", "# backoff")],
    [("pytest", 1)],
)
MIXED[9] = (
    "clean up the unused helper files and add a config key",
    ["git rm -qf src/old_helper.py", edit("src/config.py", "BASE=1")],
    [("pytest", 1)],
)
MIXED[13] = ("you forgot the cache eviction, add it", [edit("src/client.py", "cache={}")], [("pytest", 1)])
MIXED[17] = (
    "remove scratch files, format the code",
    ["rm -f scratch.txt", edit("src/client.py", "# fmt")],
    [("ruff format", 1)],
)


class Session:
    """One agent's view of a session: what each hook said, by the rules of that agent."""

    def __init__(self, agent, repo, capsys, monkeypatch):
        self.agent, self.repo, self.capsys, self.monkeypatch = agent, repo, capsys, monkeypatch
        self.heard: list[str] = []
        self.blocks: list[tuple[int, str]] = []

    def hook(self, event, **payload):
        key = "conversation_id" if self.agent == "cursor" else "session_id"
        self.monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({key: "s1", **payload})))
        if self.agent == "grok":
            self.monkeypatch.setenv("GROK_HOOK_EVENT", event)
        self.capsys.readouterr()
        main(["hook", event, "--agent", self.agent])
        return self.capsys.readouterr().out.strip()

    def stop_text(self, out):
        if not out:
            return None
        if self.agent in ("claude", "codex", "grok"):
            data = json.loads(out)
            return data.get("reason") if data.get("decision") == "block" else None
        if self.agent == "cursor":
            return json.loads(out).get("followup_message")
        return out

    def begin(self):
        (self.repo / "src").mkdir()
        (self.repo / "tests").mkdir()
        (self.repo / "src/old_helper.py").write_text("a\n")
        (self.repo / "src/net.py").write_text("b\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "code")
        (self.repo / "scratch.txt").write_text("tmp\n")
        self.heard.append(self.hook("session-start", source="startup"))

    def shell(self, command):
        subprocess.run(command, shell=True, cwd=self.repo, capture_output=True, check=False)

    def tool(self, command, ok):
        event = "PostToolUse" if ok else "PostToolUseFailure"
        self.heard.append(
            self.hook(
                "after-shell",
                hook_event_name=event,
                tool_name="Bash",
                tool_input={"command": command},
                command=command,
                tool_response={"exit_code": 0 if ok else 1},
            )
        )

    def turn(self, number, prompt, steps, commands, then=None):
        """One owner prompt to one stop. Return what the stop said."""
        self.heard.append(self.hook("prompt", hook_event_name="UserPromptSubmit", prompt=prompt))
        for step in steps:
            self.shell(step)
        for command, ok in commands:
            self.tool(command, ok)
        extra = {"loop_count": 0, "status": "completed"} if self.agent == "cursor" else {}
        said = self.stop_text(self.hook("stop", hook_event_name="Stop", **extra))
        if said:
            self.blocks.append((number, said))
            if then:
                then()
            again = {"loop_count": 1} if self.agent == "cursor" else {"stop_hook_active": True}
            self.hook("stop", hook_event_name="Stop", **again)
        return said

    def replay(self, turns, then=None):
        for number, (prompt, steps, commands) in enumerate(turns, 1):
            self.turn(number, prompt, steps, commands, then)


@pytest.fixture
def session(repo, mem, capsys, monkeypatch, request):
    return Session(request.param, repo, capsys, monkeypatch)


def write_a_fact():
    assert main(["add", "The retry loop backs off.", "--basis", "seen", "--source", "s:1"]) == 0


@pytest.mark.parametrize("session", AGENTS, indirect=True)
@pytest.mark.parametrize("turns", [PLAIN, MIXED], ids=["plain", "mixed"])
def test_twenty_ordinary_turns_block_at_most_three_times(session, turns):
    session.begin()
    session.replay(turns)
    assert len(session.blocks) <= 3, [(number, said[:80]) for number, said in session.blocks]


@pytest.mark.parametrize("session", AGENTS, indirect=True)
def test_plain_work_hears_one_reminder_and_no_stop_blocks_for_it(session):
    session.begin()
    session.replay(PLAIN)
    assert session.blocks == []
    assert sum(REMINDER in line for line in session.heard) == 1


@pytest.mark.parametrize("session", AGENTS, indirect=True)
def test_a_real_event_at_turn_15_is_named_after_an_earlier_fact(session):
    session.begin()
    session.replay(PLAIN[:2])
    write_a_fact()
    session.replay(PLAIN[2:14])
    session.shell("git revert --no-edit HEAD")
    said = session.turn(15, *PLAIN[14])
    assert said and "A revert" in said


@pytest.mark.parametrize("session", ["claude"], indirect=True)
@pytest.mark.parametrize(
    ("prompt", "steps", "commands", "named"),
    [
        (
            "you forgot the cache eviction, add it",
            [edit("src/client.py", "cache={}")],
            [],
            "The owner corrected you",
        ),
        (
            "add a test for the cache",
            [],
            [("pytest", 0), ("pytest", 0), ("pytest", 1)],
            "`pytest` failed 2 times, then passed",
        ),
        ("add a test for the cache", ["rm -f scratch.txt"], [], "`scratch.txt`"),
        ("remove the unused helper files", ["rm -f scratch.txt"], [], "`scratch.txt`"),
    ],
    ids=["correction", "fixed", "lost", "lost-not-the-file-asked-for"],
)
def test_each_event_blocks_after_a_quiet_session_with_a_fact(
    session, prompt, steps, commands, named
):
    session.begin()
    session.replay(PLAIN[:2])
    write_a_fact()
    said = session.turn(3, prompt, steps, commands)
    assert said and named in said


@pytest.mark.parametrize("session", ["claude"], indirect=True)
def test_a_command_fixed_twice_is_named_once(session):
    session.begin()
    red_green = [("pytest", 0), ("pytest", 0), ("pytest", 1)]
    assert "then passed" in session.turn(1, "add a test", [], red_green)
    assert session.turn(2, "add one more test", [], red_green) is None


@pytest.mark.parametrize("session", ["claude"], indirect=True)
def test_a_failure_that_has_not_passed_is_no_event(session):
    session.begin()
    assert session.turn(1, "add a test", [], [("pytest", 0), ("pytest", 0)]) is None


@pytest.mark.parametrize("session", ["claude"], indirect=True)
@pytest.mark.parametrize(
    "prompt",
    [
        "remove scratch files, format the code",
        "delete the scratch file",
        "please get rid of scratch files.",
        "clean up the scratch files and add a config key",
        "rm scratch.txt",
        "what is in scratch.txt",
    ],
)
def test_a_lost_file_the_owner_asked_about_is_no_event(session, prompt):
    session.begin()
    assert session.turn(1, prompt, ["rm -f scratch.txt"], []) is None


@pytest.mark.parametrize("session", ["claude"], indirect=True)
@pytest.mark.parametrize(
    "prompt",
    [
        "do not delete scratch files",
        "should we remove scratch files?",
        "clean up the scratch logic",
        "remove the retry helper, then add a scratch pad",
        "delete the unused files",
    ],
)
def test_a_lost_file_the_owner_did_not_ask_to_remove_is_an_event(session, prompt):
    session.begin()
    said = session.turn(1, prompt, ["rm -f scratch.txt"], [])
    assert said and LOST in said


@pytest.mark.parametrize("session", ["claude"], indirect=True)
def test_a_lost_file_named_in_a_correction_is_the_correction_alone(session):
    session.begin()
    said = session.turn(1, "you deleted scratch.txt", ["rm -f scratch.txt"], [])
    assert "The owner corrected you" in said
    assert LOST not in said


@pytest.mark.parametrize("session", ["claude"], indirect=True)
def test_a_fact_written_first_means_no_reminder(session):
    session.begin()
    write_a_fact()
    session.replay(PLAIN[:4])
    assert not any(REMINDER in line for line in session.heard)


@pytest.mark.parametrize("session", ["claude"], indirect=True)
def test_a_fact_written_before_the_reminder_arrives_ends_it(session):
    session.begin()
    session.replay(PLAIN[:1])
    write_a_fact()
    session.replay(PLAIN[1:3])
    assert not any(REMINDER in line for line in session.heard)


def test_the_generic_adapter_has_only_stop_so_the_reminder_arrives_there(
    repo, mem, capsys, monkeypatch
):
    def stop():
        monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "s1"}'))
        code = main(["hook", "stop", "--agent", "generic"])
        return code, capsys.readouterr().err

    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "s1"}'))
    main(["hook", "session-start", "--agent", "generic"])
    capsys.readouterr()
    (repo / "README.md").write_text("changed\n")
    code, err = stop()
    assert code == 1
    assert REMINDER in err
    (repo / "README.md").write_text("changed again\n")
    assert stop() == (0, "")
