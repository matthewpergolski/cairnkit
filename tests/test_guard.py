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
