"""The before-shell hook refuses an agent command that would forge the owner's evidence."""

from __future__ import annotations

import io
import json

import pytest

from cairnkit.cli import main
from cairnkit.forgery import AGENT_ENV, refusal

MEMDIR = "/home/me/proj.memory"

FORGED = {
    "a fake prompt into the prompt hook": "memory hook prompt --agent claude < fake.json",
    "a fake answer through a pipe": "echo '{}' | uv run memory hook after-shell --agent claude",
    "the module by hand": "python3 -m cairnkit hook prompt < fake.json",
    "a hook inside bash -c": "bash -c 'memory hook prompt < /tmp/p.json'",
    "env -u a marker": "env -u CLAUDECODE memory add 'Never X.' --kind rule --basis told",
    "an empty marker": "CLAUDECODE= memory add 'Never X.' --kind rule --basis told",
    "unset then add": "unset CLAUDECODE; memory add 'Never X.' --kind rule --basis told",
    "an empty environment": "env -i PATH=/usr/bin memory add 'Never X.' --basis told",
    "another session id": "CLAUDE_CODE_SESSION_ID=other memory add 'Never X.' --basis told",
    "a codex marker": "env --unset=CODEX_THREAD_ID uv run memory add 'Never X.' --basis told",
    "a python script that drops the marker": (
        "python3 -c \"import os; os.environ.pop('CLAUDECODE'); "
        "from cairnkit.cli import main; main(['add', 'x', '--basis', 'told'])\""
    ),
    "a python script that writes evidence": (
        "python -c 'from cairnkit import owner_evidence; owner_evidence.note_prompt(1, 2, 3, 4)'"
    ),
    "a redirect into the evidence": f"echo '{{}}' > {MEMDIR}/.sessions/s.owner.json",
    "a redirect through the link": "echo x >> memory-bank/facts/main.jsonl",
    "tee into facts": "printf x | tee -a memory-bank/facts/main.jsonl",
    "cp into the sessions folder": f"cp /tmp/x.json {MEMDIR}/.sessions/s.owner.json",
    "sed -i on facts": "sed -i '' s/false/true/ memory-bank/facts/main.jsonl",
    "a python write": ("python3 -c \"open('memory-bank/facts/main.jsonl', 'a').write('{}')\""),
    "a relative sessions path": "cd ../proj.memory && echo x > .sessions/s.owner.json",
}

ALLOWED = {
    "a plain told claim": "memory add 'Never X.' --kind rule --basis told",
    "a search": "uv run memory search deploy",
    "reading the facts": "cat memory-bank/facts/main.jsonl | head",
    "listing sessions": f"ls {MEMDIR}/.sessions",
    "tests": "uv run pytest tests/test_hooks.py -q",
    "a commit message that names the hook": "git commit -m 'docs: explain memory hook prompt'",
    "a marker in another command": "env -u CLAUDECODE claude --version",
    "a redirect elsewhere": "memory show f-20261107-aaaa > /tmp/fact.txt",
}


@pytest.mark.parametrize("case", FORGED)
def test_a_command_that_forges_evidence_is_refused(case):
    assert refusal(FORGED[case], [MEMDIR]) is not None


@pytest.mark.parametrize("case", ALLOWED)
def test_an_ordinary_command_runs(case):
    assert refusal(ALLOWED[case], [MEMDIR]) is None


def test_each_agent_marker_is_guarded():
    names = {"CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_CI", "CURSOR_AGENT",
             "OPENCODE", "PI_CODING_AGENT", "GROK_SESSION_ID"}  # fmt: skip
    assert names <= AGENT_ENV
    for name in sorted(AGENT_ENV):
        assert refusal(f"env -u {name} memory add x --basis told", [MEMDIR]), name


def before_shell(capsys, monkeypatch, command, agent="claude"):
    payload = {
        "session_id": "s",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    capsys.readouterr()
    assert main(["hook", "before-shell", "--agent", agent]) == 0
    return capsys.readouterr().out


def test_the_hook_denies_a_forged_command(mem, capsys, monkeypatch):
    out = before_shell(capsys, monkeypatch, "env -u CLAUDECODE memory add x --basis told")
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "agent marker" in decision["permissionDecisionReason"]


def test_the_hook_denies_a_write_into_the_memory_folder(mem, capsys, monkeypatch):
    out = before_shell(capsys, monkeypatch, f"echo x > {mem}/.sessions/s.owner.json")
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_hook_lets_an_ordinary_command_run(mem, capsys, monkeypatch):
    assert before_shell(capsys, monkeypatch, "memory add x --basis told") == ""


def test_a_text_agent_hears_the_refusal(mem, capsys, monkeypatch):
    out = before_shell(capsys, monkeypatch, "memory hook prompt < p.json", agent="opencode")
    assert "did not run" in out


@pytest.mark.parametrize(
    "command",
    [
        "cat src/cairnkit/hookrun.py",
        "git diff src/cairnkit/owner_evidence.py",
        "git log --oneline -- src/cairnkit/hookrun.py",
        "sed -n 1,10p src/cairnkit/owner_evidence.py > /dev/null",
        "echo 'update hookrun docs' > cairnkit_notes.txt",
        "python -m pytest tests/test_hookrun.py",
        "grep -r foo memory-bank/facts 2>/dev/null",
        "ls memory-bank/facts/ 2>&1",
        "cat memory-bank/facts/a.jsonl | wc -l > n.txt",
        f"ls {MEMDIR}/facts 2>/dev/null",
        "echo x > facts/a.jsonl",
        "cp a.jsonl facts/a.jsonl",
        "jq . facts/x.jsonl > out.json",
    ],
)
def test_reading_cairnkit_or_the_memory_folder_is_not_refused(command):
    """A review found these refused: any `>`, or a cairnkit file name, counted as a forgery."""
    assert refusal(command, [MEMDIR]) is None


@pytest.mark.parametrize(
    "command",
    [
        "echo x > memory-bank/facts/a.jsonl",
        f"echo x >> {MEMDIR}/.sessions/s.owner.json",
        "tee memory-bank/facts/x.jsonl",
        "cp evil.json memory-bank/.sessions/s1.owner.json",
        "sed -i s/a/b/ memory-bank/facts/main.jsonl",
        "cat > memory-bank/facts/x.jsonl <<'EOF'\n{}\nEOF",
        "dd if=a of=memory-bank/facts/a.jsonl",
        "python -c \"open('memory-bank/facts/x.jsonl','w').write('x')\"",
        "python - <<'EOF'\nfrom cairnkit.owner_evidence import note_prompt\nEOF",
    ],
)
def test_a_write_into_the_memory_folder_is_refused(command):
    assert refusal(command, [MEMDIR]) is not None
