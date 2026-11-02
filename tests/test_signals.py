"""The tool names events to the agent. It writes no fact itself."""

from __future__ import annotations

import io
import json

import pytest
from conftest import git, make_fact, write_facts

from cairnkit.cli import main
from cairnkit.loopbreak import command_from_payload
from cairnkit.memory import Memory
from cairnkit.paths import find_project


def hook(capsys, monkeypatch, event, payload, agent="claude"):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    capsys.readouterr()
    code = main(["hook", event, "--agent", agent])
    out = capsys.readouterr()
    assert code == 0 or event == "stop"
    return out.out


def start(capsys, monkeypatch, **extra):
    return hook(capsys, monkeypatch, "session-start", {"session_id": "s", **extra})


def facts_on_disk(mem):
    return sum(p.read_text().count("\n") for p in (mem / "facts").glob("*.jsonl"))


def bash(command, event):
    payload = {"session_id": "s", "hook_event_name": event, "tool_name": "Bash"}
    payload["tool_input"] = {"command": command}
    if event == "PostToolUseFailure":
        payload |= {"error": f"Exit code 1\n{command} broke", "is_interrupt": False}
    else:
        payload["tool_response"] = {
            "stdout": "ok",
            "stderr": "warning: noisy",
            "interrupted": False,
        }
    return payload


def test_a_claude_failure_is_read_from_its_failure_event():
    assert command_from_payload(bash("npm test", "PostToolUseFailure")) == ("npm test", False)


def test_a_claude_success_with_stderr_is_not_a_failure():
    assert command_from_payload(bash("npm test", "PostToolUse")) == ("npm test", True)


def test_an_interrupt_is_not_a_failure():
    payload = bash("npm test", "PostToolUseFailure") | {"is_interrupt": True}
    assert command_from_payload(payload) is None


def test_a_success_of_another_tool_does_not_reset_a_failing_command():
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_response": {"a": 1}}
    assert command_from_payload(payload) is None


def test_codex_failure_text_is_read():
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_input": {"command": "make"},
        "tool_response": "Process exited with code 2\nboom",
    }
    assert command_from_payload(payload) == ("make", False)


def test_a_cursor_shell_result_with_no_exit_code_says_nothing():
    assert command_from_payload({"command": "make", "output": "text"}) is None


def test_three_failures_reach_the_agent_on_the_failure_event(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    out = ""
    for _ in range(3):
        out = hook(capsys, monkeypatch, "after-shell", bash("make", "PostToolUseFailure"))
    context = json.loads(out)["hookSpecificOutput"]
    assert context["hookEventName"] == "PostToolUseFailure"
    assert "failed 3 times" in context["additionalContext"]


def test_stop_names_a_fix_after_repeated_failures_and_writes_no_fact(
    repo, mem, capsys, monkeypatch
):
    start(capsys, monkeypatch)
    before = facts_on_disk(mem)
    for _ in range(2):
        hook(capsys, monkeypatch, "after-shell", bash("make", "PostToolUseFailure"))
    hook(capsys, monkeypatch, "after-shell", bash("make", "PostToolUse"))
    out = hook(capsys, monkeypatch, "stop", {"session_id": "s"})
    assert "`make` failed 2 times, then passed" in json.loads(out)["reason"]
    assert facts_on_disk(mem) == before
    assert hook(capsys, monkeypatch, "stop", {"session_id": "s"}) == ""


def test_stop_names_a_revert_even_after_a_fact_was_written(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-qm", "Add a")
    git(repo, "revert", "--no-edit", "HEAD")
    assert main(["add", "A note.", "--basis", "seen", "--source", "session:1"]) == 0
    out = hook(capsys, monkeypatch, "stop", {"session_id": "s"})
    assert 'Revert "Add a"' in json.loads(out)["reason"]


def test_a_fact_from_another_branch_reaches_a_running_session(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    monkeypatch.setenv("MEMORY_WRITER", "other")
    assert main(["add", "Learned elsewhere.", "--basis", "seen", "--source", "session:1"]) == 0
    monkeypatch.delenv("MEMORY_WRITER")
    out = hook(capsys, monkeypatch, "prompt", {"session_id": "s"})
    assert "Learned elsewhere." in out
    assert "Learned elsewhere." not in hook(capsys, monkeypatch, "prompt", {"session_id": "s"})


def test_a_fact_that_this_writer_added_is_not_repeated(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    assert main(["add", "Mine.", "--basis", "seen", "--source", "session:1"]) == 0
    assert hook(capsys, monkeypatch, "prompt", {"session_id": "s"}) == ""


def test_an_old_trap_arrives_when_its_area_is_first_changed(repo, mem, capsys, monkeypatch):
    crowd = [
        make_fact(f"f-20261001-{i:04x}", " ".join(["word"] * 40) + f" n{i}", area="busy")
        for i in range(30)
    ]
    trap = make_fact(
        "f-20200101-0001",
        "Payments retry twice.",
        kind="trap",
        area="payments",
        learned_at="2020-01-01T00:00:00+00:00",
    )
    crowd += [
        make_fact(f"f-20200102-{i:04x}", f"Old trap {i}.", kind="trap", area=f"a{i}")
        for i in range(20)
    ]
    write_facts(mem, [*crowd, trap])
    text = start(capsys, monkeypatch)
    folder = repo / "payments"
    folder.mkdir()
    (folder / "x.py").write_text("x\n")
    git(repo, "add", "payments/x.py")
    out = hook(capsys, monkeypatch, "prompt", {"session_id": "s"})
    if "f-20200101-0001" not in text:
        assert "Payments retry twice." in out
    assert "Payments retry twice." not in hook(capsys, monkeypatch, "prompt", {"session_id": "s"})


def test_a_compaction_keeps_the_session_and_loads_again(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    for _ in range(2):
        hook(capsys, monkeypatch, "after-shell", bash("make", "PostToolUseFailure"))
    start(capsys, monkeypatch, source="compact")
    hook(capsys, monkeypatch, "after-shell", bash("make", "PostToolUse"))
    out = hook(capsys, monkeypatch, "stop", {"session_id": "s"})
    assert "`make` failed 2 times" in json.loads(out)["reason"]


def test_add_names_a_fact_that_may_now_be_stale_and_ends_nothing(mem, capsys):
    add = ["--area", "deploy", "--basis", "seen", "--source", "session:1"]
    assert main(["add", "The deploy pool holds 10 workers per host.", *add]) == 0
    old = capsys.readouterr().out.strip().split()[-1]
    assert main(["add", "The deploy pool now holds 40 workers per region.", *add]) == 0
    out = capsys.readouterr().out
    assert f"check: {old}" in out
    assert Memory.open(find_project(), None).states[old]["status"] == "active"


def test_add_in_the_default_area_names_no_conflict(mem, capsys):
    add = ["--basis", "seen", "--source", "session:1"]
    assert main(["add", "The deploy pool holds 10 workers per host.", *add]) == 0
    capsys.readouterr()
    assert main(["add", "The deploy pool now holds 40 workers per region.", *add]) == 0
    assert "check:" not in capsys.readouterr().out


def test_install_wires_the_failure_and_prompt_events(repo, mem):
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    events = json.loads((repo / ".claude" / "settings.local.json").read_text())["hooks"]
    assert {"PostToolUseFailure", "PostToolUse", "UserPromptSubmit"} <= set(events)
    assert main(["hooks", "install", "--agent", "codex"]) == 0
    codex = json.loads((repo / ".codex" / "hooks.json").read_text())["hooks"]
    assert "PostToolUseFailure" not in codex
    assert "compact" in codex["SessionStart"][0]["matcher"]
    assert main(["hooks", "install", "--agent", "cursor"]) == 0
    cursor = json.loads((repo / ".cursor" / "hooks.json").read_text())["hooks"]
    assert {"postToolUseFailure", "preCompact"} <= set(cursor)


def test_a_stored_trap_for_a_staged_file_reaches_git_output(repo, mem, capsys):
    write_facts(
        mem, [make_fact("f-20261001-0001", "x.py: Retries double bill.", kind="trap", area="pay")]
    )
    folder = repo / "pay"
    folder.mkdir()
    (folder / "x.py").write_text("x\n")
    git(repo, "add", "pay/x.py")
    capsys.readouterr()
    assert main(["hook", "pre-commit"]) == 0
    assert "x.py: Retries double bill." in capsys.readouterr().err


def test_a_trap_in_another_area_says_nothing_at_commit(repo, mem, capsys):
    write_facts(
        mem, [make_fact("f-20261001-0001", "Retries double bill.", kind="trap", area="pay")]
    )
    (repo / "x.py").write_text("x\n")
    git(repo, "add", "x.py")
    capsys.readouterr()
    assert main(["hook", "pre-commit"]) == 0
    assert capsys.readouterr().err == ""


def test_a_subagent_gets_the_load_and_writes_no_state(repo, mem, capsys, monkeypatch):
    write_facts(mem, [make_fact("f-20261001-0001", "A stored fact.")])
    out = hook(capsys, monkeypatch, "subagent-start", {"session_id": "sub"})
    context = json.loads(out)["hookSpecificOutput"]
    assert context["hookEventName"] == "SubagentStart"
    assert "A stored fact." in context["additionalContext"]
    assert not (mem / ".sessions" / "sub.json").exists()


def test_native_memory_is_named_once_and_copied_never(repo, mem, capsys, monkeypatch):
    from pathlib import Path

    from cairnkit import native

    store = native._claude_store(repo)
    store.mkdir(parents=True)
    (store / "MEMORY.md").write_text("- index\n")
    (store / "note.md").write_text("A native note.\n")
    assert str(store).startswith(str(Path.home()))
    before = facts_on_disk(mem)
    assert "1 new note" in start(capsys, monkeypatch)
    assert "new note" not in start(capsys, monkeypatch)
    (store / "two.md").write_text("Another.\n")
    assert "1 new note" in start(capsys, monkeypatch)
    assert facts_on_disk(mem) == before


def test_no_native_memory_says_nothing(repo, mem, capsys, monkeypatch):
    assert "new note" not in start(capsys, monkeypatch)


def elsewhere_fact(number, **extra):
    return make_fact(
        f"f-20261101-{number:04x}",
        f"Elsewhere number {number}.",
        writer="other",
        learned_at="2099-01-01T00:00:00+00:00",
        **extra,
    )


def open_branch(repo):
    """A branch named `other` with work that the default branch does not hold."""
    git(repo, "checkout", "-q", "-b", "other")
    (repo / "other.txt").write_text("x\n")
    git(repo, "add", "other.txt")
    git(repo, "commit", "-qm", "Work on the other branch")
    git(repo, "checkout", "-q", "main")


def touch_area(repo, area):
    folder = repo / area
    folder.mkdir()
    (folder / "x.py").write_text("x\n")
    git(repo, "add", f"{area}/x.py")


def prompt(capsys, monkeypatch):
    return hook(capsys, monkeypatch, "prompt", {"session_id": "s"})


def stop(capsys, monkeypatch):
    return hook(capsys, monkeypatch, "stop", {"session_id": "s"})


def fail(capsys, monkeypatch, times=1):
    out = ""
    for _ in range(times):
        out = hook(capsys, monkeypatch, "after-shell", bash("make", "PostToolUseFailure"))
    return out


def test_facts_past_the_line_limit_are_counted_and_named(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    write_facts(mem, [elsewhere_fact(i) for i in range(8)])
    out = prompt(capsys, monkeypatch)
    assert out.count("Elsewhere number") == 5
    assert "and 3 more" in out
    assert "memory show" in out
    hidden = [i for i in range(8) if f"Elsewhere number {i}." not in out]
    assert len(hidden) == 3
    assert all(f"f-20261101-{i:04x}" in out for i in hidden)
    assert prompt(capsys, monkeypatch) == ""


def test_matches_past_the_line_limit_are_counted_and_named(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    facts = [
        make_fact(f"f-20261001-{i:04x}", f"Payments note {i}.", area="payments") for i in range(8)
    ]
    write_facts(mem, facts)
    touch_area(repo, "payments")
    out = prompt(capsys, monkeypatch)
    assert out.count("Payments note") == 5
    assert "and 3 more" in out
    hidden = [i for i in range(8) if f"Payments note {i}." not in out]
    assert len(hidden) == 3
    assert all(f"f-20261001-{i:04x}" in out for i in hidden)
    assert prompt(capsys, monkeypatch) == ""


def test_a_short_note_of_another_branch_is_not_named_for_changed_files(
    repo, mem, capsys, monkeypatch
):
    open_branch(repo)
    start(capsys, monkeypatch)
    note = {"area": "payments", "scope": "short"}
    write_facts(
        mem,
        [
            make_fact("f-20261001-0001", "Note of a branch.", until_branch_merged="other", **note),
            make_fact("f-20261001-0002", "Note of a writer.", writer="other", **note),
            make_fact("f-20261001-0003", "Note of mine.", until_branch_merged="main", **note),
        ],
    )
    touch_area(repo, "payments")
    out = prompt(capsys, monkeypatch)
    assert "Note of mine." in out
    assert "Note of a branch." not in out
    assert "Note of a writer." not in out


def test_a_short_note_of_another_branch_is_not_news(repo, mem, capsys, monkeypatch):
    open_branch(repo)
    start(capsys, monkeypatch)
    write_facts(mem, [elsewhere_fact(1, scope="short", until_branch_merged="other")])
    assert prompt(capsys, monkeypatch) == ""


def test_a_short_note_of_another_branch_is_not_a_trap_for_this_commit(repo, mem, capsys):
    open_branch(repo)
    trap = {"kind": "trap", "area": "pay", "scope": "short", "until_branch_merged": "other"}
    write_facts(mem, [make_fact("f-20261001-0001", "Only for that branch.", **trap)])
    touch_area(repo, "pay")
    capsys.readouterr()
    assert main(["hook", "pre-commit"]) == 0
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    "subject",
    [
        "feat: add revert button",
        "docs: explain how to revert a deploy",
        "fix: the undo code reverts too much",
        "Reverting is now one click",
    ],
)
def test_a_subject_that_only_mentions_a_revert_says_nothing(
    repo, mem, capsys, monkeypatch, subject
):
    start(capsys, monkeypatch)
    git(repo, "commit", "-q", "--allow-empty", "-m", subject)
    assert "A revert:" not in stop(capsys, monkeypatch)


@pytest.mark.parametrize(
    "subject", ['Revert "Add a"', "revert: add a", "revert(api): add a", "Revert the cache change"]
)
def test_a_real_revert_subject_is_named(repo, mem, capsys, monkeypatch, subject):
    start(capsys, monkeypatch)
    git(repo, "commit", "-q", "--allow-empty", "-m", subject)
    assert subject in json.loads(stop(capsys, monkeypatch))["reason"]


def old_revert_on_other_branch(repo, monkeypatch):
    git(repo, "checkout", "-q", "-b", "other")
    with monkeypatch.context() as patch:
        patch.setenv("GIT_COMMITTER_DATE", "2020-01-01T00:00:00+00:00")
        git(repo, "commit", "-q", "--allow-empty", "-m", 'Revert "Their change"')
    git(repo, "checkout", "-q", "main")


def test_a_revert_from_a_branch_switch_is_not_this_session(repo, mem, capsys, monkeypatch):
    old_revert_on_other_branch(repo, monkeypatch)
    start(capsys, monkeypatch)
    git(repo, "checkout", "-q", "other")
    assert "A revert:" not in stop(capsys, monkeypatch)


def test_a_revert_from_a_new_merge_is_not_this_session(repo, mem, capsys, monkeypatch):
    old_revert_on_other_branch(repo, monkeypatch)
    start(capsys, monkeypatch)
    git(repo, "merge", "-q", "--ff-only", "other")
    assert "A revert:" not in stop(capsys, monkeypatch)


def test_a_revert_on_a_branch_this_session_switched_to_is_named(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    git(repo, "checkout", "-q", "-b", "work")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-qm", "Add a")
    git(repo, "revert", "--no-edit", "HEAD")
    assert 'Revert "Add a"' in json.loads(stop(capsys, monkeypatch))["reason"]


def test_long_session_keys_with_one_prefix_do_not_share_a_state(repo, mem, capsys, monkeypatch):
    prefix = "/Users/someone/.pi/agent/sessions/" + "x" * 80
    one, two = prefix + "/one.jsonl", prefix + "/two.jsonl"
    hook(capsys, monkeypatch, "session-start", {"session_id": one})
    failure = bash("make", "PostToolUseFailure") | {"session_id": one}
    for _ in range(2):
        hook(capsys, monkeypatch, "after-shell", failure)
    passed = bash("make", "PostToolUse") | {"session_id": one}
    hook(capsys, monkeypatch, "after-shell", passed)
    hook(capsys, monkeypatch, "session-start", {"session_id": two})
    out = hook(capsys, monkeypatch, "stop", {"session_id": one})
    assert "`make` failed 2 times" in json.loads(out)["reason"]
    assert len(list((mem / ".sessions").glob("*.json"))) == 2


def test_keys_that_differ_only_in_a_replaced_character_do_not_share_a_state(repo, mem):
    from cairnkit.session import _path

    memory = Memory.open(find_project(), None)
    assert _path(memory, "a/b") != _path(memory, "a-b")
    assert _path(memory, "plain-id").name == "plain-id.json"
    assert len(_path(memory, "z" * 500).name) <= 120


def test_a_failed_edit_is_not_a_failed_command_at_stop(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    edit = {"session_id": "s", "tool_name": "Edit"}
    failed = edit | {"hook_event_name": "PostToolUseFailure", "error": "no match"}
    for _ in range(2):
        hook(capsys, monkeypatch, "after-shell", failed)
    passed = edit | {"hook_event_name": "PostToolUse", "tool_response": {"ok": True}}
    hook(capsys, monkeypatch, "after-shell", passed)
    assert "`Edit`" not in stop(capsys, monkeypatch)


def test_a_loop_nudge_reaches_the_agent_once(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    assert "failed 3 times" in fail(capsys, monkeypatch, 3)
    assert "Stop retrying it" not in stop(capsys, monkeypatch)


def test_a_fact_this_session_wrote_is_not_news_after_a_branch_switch(
    repo, mem, capsys, monkeypatch
):
    start(capsys, monkeypatch)
    assert main(["add", "Mine, then I moved.", "--basis", "seen", "--source", "session:1"]) == 0
    git(repo, "checkout", "-q", "-b", "next")
    assert "Mine, then I moved." not in prompt(capsys, monkeypatch)


def test_a_fact_from_a_branch_this_session_never_used_is_still_news(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    git(repo, "checkout", "-q", "-b", "next")
    prompt(capsys, monkeypatch)
    monkeypatch.setenv("MEMORY_WRITER", "third")
    assert main(["add", "From a third branch.", "--basis", "seen", "--source", "session:1"]) == 0
    monkeypatch.delenv("MEMORY_WRITER")
    assert "From a third branch." in prompt(capsys, monkeypatch)


def test_a_resumed_session_keeps_its_events(repo, mem, capsys, monkeypatch):
    start(capsys, monkeypatch)
    fail(capsys, monkeypatch, 2)
    start(capsys, monkeypatch, source="resume")
    hook(capsys, monkeypatch, "after-shell", bash("make", "PostToolUse"))
    assert "`make` failed 2 times" in json.loads(stop(capsys, monkeypatch))["reason"]


def boom(*args, **kwargs):
    raise RuntimeError("boom")


@pytest.mark.parametrize(
    ("broken", "kept"),
    [
        ("hookrun.read_health", ("`make` failed 2 times",)),
        ("signals.stop_nudge", ("`make` failed 2 times",)),
        ("hookrun.mark_reminder", ("`make` failed 2 times",)),
    ],
)
def test_one_broken_step_leaves_the_others_at_stop(repo, mem, capsys, monkeypatch, broken, kept):
    start(capsys, monkeypatch)
    fail(capsys, monkeypatch, 2)
    hook(capsys, monkeypatch, "after-shell", bash("make", "PostToolUse"))
    (repo / "new.py").write_text("x\n")
    monkeypatch.setattr(f"cairnkit.{broken}", boom)
    reason = json.loads(stop(capsys, monkeypatch))["reason"]
    assert all(text in reason for text in kept)


def test_a_bad_memory_path_file_does_not_fail_a_commit(repo, mem):
    (repo / ".memory-path").write_bytes(b"\xff\xfe not text\n")
    (repo / "x.py").write_text("x\n")
    git(repo, "add", "x.py")
    assert main(["hook", "pre-commit"]) == 0


def test_a_bad_memory_path_file_still_refuses_private_paths(repo, mem, capsys):
    (repo / ".memory-path").write_bytes(b"\xff\xfe not text\n")
    git(repo, "add", "-f", ".memory-path")
    capsys.readouterr()
    assert main(["hook", "pre-commit"]) == 1
    assert "commit refused" in capsys.readouterr().err


@pytest.mark.parametrize("event", ["session-start", "stop", "prompt", "after-shell"])
def test_a_bad_memory_path_file_does_not_break_an_agent_hook(repo, mem, monkeypatch, event):
    (repo / ".memory-path").write_bytes(b"\xff\xfe not text\n")
    monkeypatch.setattr("sys.stdin", io.StringIO('{"session_id": "s"}'))
    assert main(["hook", event, "--agent", "claude"]) == 0
