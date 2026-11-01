"""Audit findings: model names in the guard, hooks with a Python that is gone, false enforcement.

The attribution lines and identities here are fixtures that the guard must refuse.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from conftest import git, make_fact, write_facts

from cairnkit import githook, refresh
from cairnkit.cli import main
from cairnkit.paths import find_project

RULE = "Never add a Co-authored-by trailer that names an AI model."
ADD_RULE = ["add", RULE, "--kind", "rule", "--area", "git", "--basis", "told", "--source", "s:1"]
HOOK = ("hooks", "install", "--agent", "generic")
GONE = "/no/such/python3"

REFUSED_LINES = [
    "Made-with: Cursor",
    "Made with Claude Code",
    "Assisted-by: Claude",
    "Assisted-by: Claude:claude-opus-5-5",
    "Written by Claude",
    "Signed-off-by: Claude <noreply@anthropic.com>",
    "Co-Authored-By: Claude <noreply@anthropic.com>",
    "Co-authored-by: Claude <noreply@example.com>",
    "Co-authored-by: Opus <no-reply@example.com>",
    "Co-Authored-By: Fable",
    "Co-Authored-By: Fable <noreply@anthropic.com>",
    "Co-Authored-By: Opus",
    "Co-Authored-By: Opus 4.7",
    "Co-Authored-By: Opus 4.7 (1M context) <noreply@anthropic.com>",
    "Co-Authored-By: Sonnet 5 <jane@example.com>",
    "Co-Authored-By: Haiku",
    "Co-Authored-By: Claude Opus 5.5 <jane@example.com>",
    "Co-Authored-By: claude-opus-5-5",
    "Co-Authored-By: DeepSeek",
    "Co-Authored-By: GPT-5.1 <jane@example.com>",
    "Co-Authored-By: Gemini 2.5 <jane@example.com>",
    "Co-Authored-By: Grok <jane@example.com>",
    "Co-Authored-By: Cursor <cursoragent@cursor.com>",
    "Co-authored-by: copilot-swe-agent[bot] <1+Copilot@users.noreply.github.com>",
]
ALLOWED_LINES = [
    "Co-authored-by: Claude Monet <claude@monet.example>",
    "Co-authored-by: Claude <claude.dupont@example.com>",
    "Co-authored-by: Fable Jones <fable@example.com>",
    "Co-authored-by: Opus Lee <opus@example.com>",
    "Co-authored-by: Sonnet Patel <sonnet@example.com>",
    "Co-authored-by: Haiku Tanaka <haiku@example.com>",
    "Co-authored-by: Cursor Smith <cursor.smith@example.com>",
    "Co-authored-by: Devin Patel <devin@example.com>",
    "Signed-off-by: Claude Shannon <cs@example.com>",
    "Assisted-by: Jane Doe <jane@example.com>",
    "Made with care in the old module.",
    "Made with cursor positioning in mind.",
    "Written by Claude Monet",
    "Add a fable to the opus docs.",
    "Fix the cursor in the haiku editor.",
]
REFUSED_NAMES = [
    ("Opus 4.7", "jane@example.com"),
    ("Fable 5", "jane@example.com"),
    ("Claude Fable", "jane@example.com"),
    ("Fable", "noreply@anthropic.com"),
    ("Claude", "noreply@example.com"),
    ("DeepSeek", "jane@example.com"),
]
ALLOWED_NAMES = [
    ("Fable Jones", "fable@example.com"),
    ("Opus", "opus@example.com"),
    ("Sonnet Patel", "sonnet@example.com"),
    ("Haiku", "haiku@example.com"),
    ("Claude", "123+claude@users.noreply.github.com"),
    ("Claude Monet", "noreply@example.com"),
]


def commit(repo, message="change", author=None):
    with (repo / "f.txt").open("a") as fh:
        fh.write("x\n")
    git(repo, "add", "f.txt")
    env = dict(os.environ)
    if author:
        env |= {"GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1]}
    return subprocess.run(
        ["git", "commit", "-q", "-F", "-"],
        cwd=repo,
        input=message,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def guarded(repo, mem):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    return repo


def test_the_guard_refuses_each_tool_and_model_line(guarded):
    wrong = [line for line in REFUSED_LINES if commit(guarded, f"x\n\n{line}\n").returncode == 0]
    assert wrong == []


def test_the_guard_allows_a_person_or_plain_words(guarded):
    wrong = [
        (line, result.stderr)
        for line in ALLOWED_LINES
        if (result := commit(guarded, f"x\n\n{line}\n")).returncode != 0
    ]
    assert wrong == []


def test_the_identity_check_knows_model_names(guarded):
    assert [w for w in REFUSED_NAMES if commit(guarded, author=w).returncode == 0] == []
    assert [w for w in ALLOWED_NAMES if commit(guarded, author=w).returncode != 0] == []


def test_a_rule_that_names_only_a_model_family_asks_for_the_guard(repo, mem):
    text = "Never add a Co-authored-by trailer that names Fable or Opus."
    assert main(["add", text, *ADD_RULE[2:]]) == 0
    assert main(HOOK) == 0
    assert (repo / ".git" / "hooks" / "commit-msg").is_file()


def _point_hooks_at(repo, python):
    for path in (repo / ".git" / "hooks").iterdir():
        if not path.name.endswith(".sample"):
            path.write_text(path.read_text().replace(sys.executable, python))


@pytest.fixture
def no_python(repo, mem):
    assert main(HOOK) == 0
    _point_hooks_at(repo, GONE)
    return repo


def test_python_gone_does_not_stop_an_unrelated_commit_and_says_so(no_python):
    result = commit(no_python)
    assert result.returncode == 0, result.stderr
    assert GONE in result.stderr
    assert "memory init --refresh" in result.stderr


@pytest.mark.parametrize("path", ["memory-bank", ".memory-path"])
def test_python_gone_still_refuses_a_private_path(no_python, path):
    if path == ".memory-path":
        (no_python / path).write_text("../proj.memory\n")
    git(no_python, "add", "-f", path)
    result = subprocess.run(
        ["git", "commit", "-q", "-m", "leak"], cwd=no_python, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert path in result.stderr
    assert path not in git(no_python, "ls-tree", "-r", "--name-only", "HEAD")


def test_a_python_without_the_tool_does_not_stop_a_commit(repo, mem, tmp_path):
    assert main(HOOK) == 0
    fake = tmp_path / "python-without-the-tool"
    fake.write_text("#!/bin/sh\necho 'No module named cairnkit' >&2\nexit 1\n")
    fake.chmod(0o755)
    _point_hooks_at(repo, str(fake))
    result = commit(repo)
    assert result.returncode == 0, result.stderr
    assert "No module named" not in result.stderr
    assert "memory init --refresh" in result.stderr


def test_a_healthy_hook_prints_nothing_about_python(repo, mem):
    assert main(HOOK) == 0
    assert commit(repo).stderr == ""


@pytest.mark.parametrize("command", ["status", "check"])
def test_status_and_check_say_the_hook_python_is_gone(no_python, capsys, command):
    capsys.readouterr()
    assert main([command]) == 0
    out = capsys.readouterr().out
    assert GONE in out
    assert "memory init --refresh" in out
    assert "Repo files: current." not in out


def test_the_load_names_the_gone_python_and_refresh_repairs_it(no_python, capsys):
    capsys.readouterr()
    assert main(["load"]) == 0
    assert GONE in capsys.readouterr().out
    assert main(["init", "--refresh"]) == 0
    assert refresh.repo_line(find_project(), None) is None
    text = (no_python / ".git" / "hooks" / "pre-commit").read_text()
    assert GONE not in text and sys.executable in text


def test_an_agent_hook_with_a_gone_python_is_named(repo, mem, capsys):
    (repo / ".claude").mkdir()
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    path = repo / ".claude" / "settings.local.json"
    data = json.loads(path.read_text())
    path.write_text(json.dumps(data).replace(sys.executable, GONE))
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert GONE in out
    assert "Repo files: current." not in out
    assert main(["init", "--refresh"]) == 0
    assert GONE not in path.read_text()


def test_the_python_line_stays_quiet_when_nothing_is_wrong(repo, mem):
    assert main(HOOK) == 0
    assert refresh.gone_pythons(find_project()) == []


CHECK_ENFORCED = "does-not-exist"


def _rule(mem, ref):
    write_facts(mem, [make_fact("f-20261001-0001", "A rule.", kind="rule", enforced_by=ref)])


def _load(capsys):
    capsys.readouterr()
    assert main(["load"]) == 0
    out = capsys.readouterr().out
    enforced = "## Enforced rules" in out
    return out, enforced


def _workflow(repo, text):
    path = repo / ".github" / "workflows" / "ci.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.mark.parametrize(
    "ref",
    [
        f"ci:{CHECK_ENFORCED}",
        f"test:tests/{CHECK_ENFORCED}.py",
        f"githook:{CHECK_ENFORCED}",
        f"lint:{CHECK_ENFORCED}:T201",
    ],
)
def test_a_check_that_is_not_there_is_not_called_enforced(repo, mem, capsys, ref):
    _rule(mem, ref)
    out, enforced = _load(capsys)
    assert not enforced
    assert "## Advisory rules" in out
    assert f"no check found for {ref}" in out
    capsys.readouterr()
    assert main(["check"]) == 0
    assert f"enforced_by {ref}" in capsys.readouterr().out
    assert main(["check", "--strict"]) == 1


def test_a_ci_job_that_is_there_is_enforced(repo, mem, capsys):
    _workflow(repo, "jobs:\n  lint:\n    runs-on: ubuntu-latest\n")
    _rule(mem, "ci:lint")
    _, enforced = _load(capsys)
    assert enforced
    assert main(["check", "--strict"]) == 0


def test_a_ci_word_inside_another_word_does_not_count(repo, mem, capsys):
    _workflow(repo, "jobs:\n  flint-docs:\n    runs-on: ubuntu-latest\n")
    _rule(mem, "ci:lint")
    _, enforced = _load(capsys)
    assert not enforced


def test_a_test_file_that_is_there_is_enforced(repo, mem, capsys):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("")
    _rule(mem, "test:tests/test_x.py")
    assert _load(capsys)[1]


def test_a_lint_tool_that_ci_runs_is_enforced(repo, mem, capsys):
    _workflow(repo, "jobs:\n  a:\n    steps:\n      - run: uv run ruff check .\n")
    _rule(mem, "lint:ruff:T201")
    assert _load(capsys)[1]


def test_the_guard_ref_follows_the_real_guard(guarded, mem, capsys):
    _rule(mem, githook.GUARD_REF)
    assert _load(capsys)[1]
    (guarded / ".git" / "hooks" / "commit-msg").unlink()
    assert not _load(capsys)[1]


def test_a_foreign_git_hook_counts(repo, mem, capsys):
    path = repo / ".git" / "hooks" / "pre-push"
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    _rule(mem, "githook:pre-push")
    assert _load(capsys)[1]


def test_a_type_with_no_way_to_look_stays_as_written(repo, mem, capsys):
    _rule(mem, "manual:release-review")
    assert _load(capsys)[1]
    assert main(["check", "--strict"]) == 0


def test_a_hidden_hook_warns_once_and_does_not_fail_strict(guarded, mem, capsys):
    _rule(mem, githook.GUARD_REF)
    (guarded / ".githooks").mkdir()
    git(guarded, "config", "core.hooksPath", ".githooks")
    assert not _load(capsys)[1]
    capsys.readouterr()
    assert main(["check", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "warning: core.hooksPath is .githooks" in out
    assert "enforced_by" not in out


def test_advisory_lists_a_rule_whose_check_is_gone(repo, mem, capsys):
    _rule(mem, f"ci:{CHECK_ENFORCED}")
    capsys.readouterr()
    assert main(["check", "--advisory"]) == 0
    assert "1 advisory rule(s)" in capsys.readouterr().out
