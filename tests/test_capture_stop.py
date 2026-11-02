"""One blocking check at stop makes the agent capture, and it does not nag."""

from __future__ import annotations

import io
import json
import shutil
import subprocess

import pytest
from test_stop_replay import PLAIN, Session

from cairnkit.cli import main
from cairnkit.discover import CAPTURE_GUIDE
from cairnkit.instructions import text as rules_block
from cairnkit.session import WORK_GAP

AGENTS = ("claude", "codex", "cursor", "pi", "opencode")
STATEMENT = "We decided to keep the old API, because our partners rely on it."
MOMENTS = (
    "if this session ended now, what would the next agent get wrong?",
    "decided or approved",
    "promise or a limit",
    "review found",
    "purpose and its next step",
    "failure and its fix",
    "no longer true",
    "the reason and not only the change",
    "names the files",
    '`memory add "TEXT"`',
)


@pytest.fixture
def session(repo, mem, capsys, monkeypatch, request):
    made = Session(getattr(request, "param", "claude"), repo, capsys, monkeypatch)
    made.begin()
    return made


def add_a_fact():
    assert main(["add", "The queue drops jobs on restart."]) == 0


def edit(session, text="x"):
    return [f"echo {text} >> {session.repo}/README.md"]


@pytest.mark.parametrize("session", AGENTS, indirect=True)
def test_a_statement_with_no_change_blocks_once_on_each_tool_with_a_prompt_hook(session):
    said = session.turn(1, STATEMENT, [], [])
    assert said
    assert all(moment in said for moment in MOMENTS)
    assert session.turn(2, "what does the config loader read", [], []) is None


@pytest.mark.parametrize("session", [*AGENTS, "grok"], indirect=True)
def test_changed_work_blocks_the_first_stop_on_each_tool(session):
    said = session.turn(1, "format the code", edit(session), [])
    assert said
    assert all(moment in said for moment in MOMENTS)


def test_an_ordinary_prompt_with_no_change_does_not_block(session):
    assert session.turn(1, "explain what the retry loop does", [], []) is None


def test_a_fact_written_in_the_turn_answers_the_check(session):
    session.heard.append(session.hook("prompt", prompt=STATEMENT))
    add_a_fact()
    session.shell(edit(session)[0])
    assert session.stop_text(session.hook("stop")) is None


def test_a_decline_ends_that_batch_and_all_plain_work_after_it(session):
    assert session.turn(1, "add a helper", edit(session), [])
    for number in range(2, 2 * WORK_GAP + 4):
        assert session.turn(number, "add a helper", edit(session, str(number)), []) is None


def test_a_later_statement_blocks_again_after_a_decline(session):
    assert session.turn(1, "add a helper", edit(session), [])
    assert session.turn(2, "add a helper", edit(session, "two"), []) is None
    assert session.turn(3, STATEMENT, [], [])
    assert session.turn(4, "thanks", [], []) is None


def test_two_statements_before_one_stop_block_once(session):
    session.hook("prompt", prompt=STATEMENT)
    assert session.turn(1, "I prefer small commits with one change each", [], [])
    assert session.turn(2, "thanks", [], []) is None


def test_a_new_batch_after_a_fact_waits_for_the_gap_and_blocks_once(session):
    assert session.turn(1, "add a helper", edit(session), [], add_a_fact)
    blocks = [
        number
        for number in range(2, WORK_GAP + 4)
        if session.turn(number, "add a helper", edit(session, str(number)), [])
    ]
    assert blocks == [WORK_GAP + 2]


def test_no_new_work_after_the_gap_does_not_block(session):
    assert session.turn(1, "add a helper", edit(session), [], add_a_fact)
    for number in range(2, 2 * WORK_GAP + 4):
        assert session.turn(number, "explain this", [], []) is None


def test_twenty_turns_of_an_agent_that_always_writes_block_at_most_three_times(session):
    session.replay(PLAIN, add_a_fact)
    assert len(session.blocks) <= 3, [number for number, _ in session.blocks]


def test_a_continued_stop_never_blocks(session):
    session.hook("prompt", prompt=STATEMENT)
    session.shell(edit(session)[0])
    assert session.stop_text(session.hook("stop", stop_hook_active=True)) is None


def test_a_subagent_gets_no_capture_block_and_leaves_the_check_to_the_parent(session):
    session.hook("prompt", prompt=STATEMENT)
    session.shell(edit(session)[0])
    assert session.stop_text(session.hook("stop", agent_id="sub-1")) is None
    said = session.stop_text(session.hook("stop"))
    assert said
    assert all(moment in said for moment in MOMENTS)


def test_a_subagent_still_hears_its_own_event_without_the_guide(session):
    session.tool("pytest", False)
    session.tool("pytest", False)
    session.tool("pytest", True)
    said = session.stop_text(session.hook("stop", agent_id="sub-1"))
    assert "`pytest` failed 2 times, then passed" in said
    assert '`memory add "TEXT"`' in said
    assert "next agent" not in said


@pytest.mark.parametrize(
    ("failed", "passed"),
    [
        ("sh report.sh", "REPORT_LOCALE=C sh report.sh"),
        ("cd /tmp/x && sh report.sh", "cd /tmp/x && REPORT_LOCALE=C sh report.sh"),
        ("pytest", "uv run pytest"),
    ],
)
def test_a_failure_fixed_by_how_the_command_runs_is_named_once(session, failed, passed):
    session.tool(failed, False)
    session.tool(passed, True)
    said = session.stop_text(session.hook("stop"))
    assert passed in said
    assert "What fixed it?" in said
    assert "next agent" in said
    assert session.turn(2, "thanks", [], []) is None


@pytest.mark.parametrize(
    ("failed", "passed"),
    [
        ("pytest", "pytest"),
        ("pytest", "pytest -x"),
        ("git commit -m x", "git add . && git commit -m x"),
        ("sh report.sh", "cat docs/report.md"),
    ],
)
def test_red_then_green_or_another_command_is_no_event(session, failed, passed):
    session.tool(failed, False)
    session.tool(passed, True)
    assert session.stop_text(session.hook("stop")) is None


def test_the_block_comes_with_a_real_event_only_once(session):
    session.tool("pytest", False)
    session.tool("pytest", False)
    session.tool("pytest", True)
    session.shell(edit(session)[0])
    said = session.stop_text(session.hook("stop"))
    assert "then passed" in said
    assert said.count("next agent") == 1
    assert session.turn(2, "thanks", [], []) is None


@pytest.mark.parametrize("session", ["grok"], indirect=True)
def test_grok_hears_the_guide_at_the_next_tool_because_its_docs_call_stop_passive(session):
    said = session.turn(1, "format the code", edit(session), [])
    assert said
    session.tool("ls", True)
    assert sum("next agent" in line for line in session.heard) == 1


def test_generic_gets_the_guide_on_stderr_once_and_exits_one(repo, mem, capsys, monkeypatch):
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
    assert all(moment in err for moment in MOMENTS)
    (repo / "README.md").write_text("changed again\n")
    assert stop() == (0, "")


def test_the_rules_block_holds_the_guide_and_says_what_a_check_line_may_allow():
    block = rules_block()
    assert CAPTURE_GUIDE in block
    assert "fix what it reports" not in block
    assert "Each line says what to do" in block


def test_memory_instructions_prints_the_guide(mem, capsys):
    capsys.readouterr()
    assert main(["instructions"]) == 0
    assert CAPTURE_GUIDE in capsys.readouterr().out


def test_memory_add_needs_only_the_text(mem, capsys):
    capsys.readouterr()
    assert (
        main(["add", "The gateway restarts each night, so retries must outlast 40 seconds."]) == 0
    )
    assert "added " in capsys.readouterr().out


OPENCODE_DRIVER = """
import { CairnkitMemory } from "./cairnkit.js";

const said = [];
const plugin = await CairnkitMemory({
  directory: process.cwd(),
  client: {
    session: {
      get: async ({ path }) => ({ data: { parentID: path.id === "child" ? "main" : undefined } }),
      prompt: async ({ path, body }) => said.push({ id: path.id, noReply: body.noReply }),
    },
  },
});
const created = (id) => ({ event: { type: "session.created", properties: { info: { id } } } });
const idle = (id) => ({ event: { type: "session.idle", properties: { sessionID: id } } });
const message = (id) => [
  { sessionID: id },
  { parts: [{ type: "text", text: process.argv[2] }] },
];
for (const id of ["main", "child"]) await plugin.event(created(id));
said.length = 0;
await plugin["chat.message"](...message("child"));
await plugin.event(idle("child"));
const child = said.length;
await plugin["chat.message"](...message("main"));
await plugin.event(idle("main"));
await plugin.event(idle("main"));
console.log(JSON.stringify({ child, main: said.filter((item) => item.id === "main") }));
process.exit(0);
"""


def test_the_opencode_plugin_reads_the_prompt_and_spares_a_child_session(repo, mem):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    assert main(["hooks", "install", "--agent", "opencode"]) == 0
    folder = repo / ".opencode" / "plugins"
    (folder / "driver.mjs").write_text(OPENCODE_DRIVER)
    done = subprocess.run(
        [node, str(folder / "driver.mjs"), STATEMENT],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)
    assert report == {"child": 0, "main": [{"id": "main", "noReply": False}]}
