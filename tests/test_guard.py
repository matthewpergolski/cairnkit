"""The commit-msg guard.

BAD holds AI attribution lines on purpose. They are fixtures that the guard
must refuse.
"""

import subprocess

from conftest import git

from cairnkit.cli import main

BAD = [
    "Fix bug\n\nCo-authored-by: Claude <noreply@anthropic.com>\n",
    "Fix bug\n\nCo-Authored-By: GitHub Copilot <copilot@github.com>\n",
    "Fix bug\n\nGenerated with an AI coding tool\n",
    "Fix bug\n\n\U0001f916 Generated with Some Tool\n",
]
GOOD = [
    "Fix bug\n\nCo-authored-by: Jane Doe <jane@example.com>\n",
    "Add generator for config files\n",
    "Fix bug\n# Generated with comment lines is fine\n",
]


def commit(repo, message):
    (repo / "f.txt").write_text(message)
    git(repo, "add", "f.txt")
    return subprocess.run(
        ["git", "commit", "-q", "-F", "-"], cwd=repo, input=message, capture_output=True, text=True
    )


def test_guard_is_opt_in(repo, mem, capsys):
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    assert not (repo / ".git" / "hooks" / "commit-msg").exists()


def test_local_guard_rejects_ai_attribution(repo, mem, capsys):
    assert main(["hooks", "install", "--agent", "generic", "--commit-msg-guard"]) == 0
    for message in BAD:
        result = commit(repo, message)
        assert result.returncode != 0, message
        assert "refused" in result.stderr
        git(repo, "reset", "-q")
    for message in GOOD:
        assert commit(repo, message).returncode == 0, message


def test_shared_guard_is_a_tracked_file_that_needs_no_tool(repo, mem, capsys):
    code = main(["hooks", "install", "--agent", "generic", "--commit-msg-guard=shared"])
    assert code == 0
    out = capsys.readouterr().out
    hook = repo / ".githooks" / "commit-msg"
    assert hook.is_file() and hook.stat().st_mode & 0o111
    text = hook.read_text()
    assert "-m cairnkit" not in text and "python" not in text
    assert "git config core.hooksPath .githooks" in out
    pre = (repo / ".githooks" / "pre-commit").read_text()
    assert "command -v memory" in pre
    # A cloner: set the hooks path, with no memory tool on PATH.
    git(repo, "config", "core.hooksPath", ".githooks")
    env_result = subprocess.run(
        ["git", "commit", "-q", "-F", "-"],
        cwd=repo,
        input=BAD[0],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(repo),
        },
    )
    assert env_result.returncode != 0
    git(repo, "add", ".githooks")
    assert commit(repo, GOOD[0]).returncode == 0


def test_patterns_come_from_config(repo, mem, capsys):
    cfg = mem / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[commit_msg_guard]\npatterns = ["^Signed-off-by: Bot"]\n')
    assert main(["hooks", "install", "--agent", "generic", "--commit-msg-guard"]) == 0
    assert commit(repo, "x\n\nSigned-off-by: Bot <b@example.com>\n").returncode != 0
    git(repo, "reset", "-q")
    assert commit(repo, BAD[0]).returncode == 0


def test_uninstall_removes_the_local_guard(repo, mem, capsys):
    main(["hooks", "install", "--agent", "generic", "--commit-msg-guard"])
    main(["hooks", "uninstall"])
    assert not (repo / ".git" / "hooks" / "commit-msg").exists()


def test_uninstall_keeps_tracked_shared_hooks(repo, mem, capsys):
    main(["hooks", "install", "--agent", "generic", "--commit-msg-guard=shared"])
    git(repo, "config", "core.hooksPath", ".githooks")
    git(repo, "add", ".githooks")
    git(repo, "commit", "-q", "-m", "Add shared hooks")
    before = {p.name: p.read_text() for p in (repo / ".githooks").iterdir()}
    capsys.readouterr()
    assert main(["hooks", "uninstall"]) == 0
    out = capsys.readouterr().out
    assert {p.name: p.read_text() for p in (repo / ".githooks").iterdir()} == before
    assert git(repo, "status", "--porcelain", ".githooks") == ""
    assert "skip" in out and "by hand" in out
