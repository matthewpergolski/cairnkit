"""The guard against an AI author or committer, with real commits and real pushes.

The identities and lines here name AI tools on purpose. They are fixtures that the
guard must refuse.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from conftest import git

from cairnkit.cli import main

RULE = "Never add a Co-authored-by trailer that names an AI model."
ADD_RULE = ["add", RULE, "--kind", "rule", "--area", "git", "--basis", "told", "--source", "s:1"]
HOOK = ("hooks", "install", "--agent", "generic")

REFUSED = [
    ("Cursor Agent", "cursoragent@cursor.com"),
    ("Cursor Agent", "jane@example.com"),
    ("cursor", "cursoragent@cursor.com"),
    ("Jane Doe", "cursoragent@cursor.com"),
    ("Cursor", "jane@example.com"),
    ("Claude", "noreply@anthropic.com"),
    ("Claude Code", "jane@example.com"),
    ("Claude Opus 4.5", "jane@example.com"),
    ("GitHub Copilot", "copilot@github.com"),
    ("Copilot", "198982749+Copilot@users.noreply.github.com"),
    ("copilot-swe-agent[bot]", "198982749+Copilot@users.noreply.github.com"),
    ("claude[bot]", "209825114+claude[bot]@users.noreply.github.com"),
    ("cursor[bot]", "206951365+cursor[bot]@users.noreply.github.com"),
    ("devin-ai-integration[bot]", "158243242+devin-ai-integration[bot]@users.noreply.github.com"),
    ("Devin AI", "devin@cognition.ai"),
    ("Codex", "noreply@openai.com"),
    ("chatgpt-codex-connector[bot]", "1+chatgpt-codex-connector[bot]@users.noreply.github.com"),
    ("google-labs-jules[bot]", "1+google-labs-jules[bot]@users.noreply.github.com"),
    ("Gemini CLI", "jane@example.com"),
    ("Jane Doe (aider)", "jane@example.com"),
    ("opencode", "noreply@opencode.ai"),
    ("Grok Build", "jane@example.com"),
    ("Opus 4.7", "jane@example.com"),
    ("Sonnet 4.6", "jane@example.com"),
    ("GPT-5.5", "jane@example.com"),
    ("Kiro Agent", "jane@example.com"),
    ("Kiro", "noreply@kiro.dev"),
    ("kiro-agent[bot]", "1+kiro-agent[bot]@users.noreply.github.com"),
    ("Qoder", "jane@example.com"),
    ("Qoder", "noreply@qoder.com"),
    ("Cline", "noreply@cline.bot"),
    ("Cline Bot", "jane@example.com"),
    ("Roo Code", "jane@example.com"),
    ("Kilo Code", "jane@example.com"),
    ("Amp", "amp@ampcode.com"),
    ("Junie", "junie@jetbrains.com"),
    ("Trae", "noreply@trae.ai"),
    ("Zencoder", "z@zencoder.ai"),
    ("A New Tool 4.7", "jane@example.com"),
    ("Any Name", "noreply@newtool.ai"),
]
ALLOWED = [
    ("Cursor Smith", "cursor.smith@example.com"),
    ("Jane Cursor", "jane@example.com"),
    ("Cursor Agent Smith", "cas@example.com"),
    ("Claude Monet", "claude@monet.example"),
    ("Claude", "claude.dupont@example.com"),
    ("Devin Patel", "devin@example.com"),
    ("Devin", "devin@example.com"),
    ("Gemini Ruiz", "gemini@example.com"),
    ("Grok Lee", "grok@example.com"),
    ("Jane Codex", "codex@example.com"),
    ("Agent Smith", "smith@example.com"),
    ("Jane Doe", "jane@cursor.com"),
    ("Sam Lee", "sam@anthropic.com"),
    ("Pat Kim", "cursor@example.com"),
    ("GitHub", "noreply@github.com"),
    ("dependabot[bot]", "49699333+dependabot[bot]@users.noreply.github.com"),
    ("renovate[bot]", "29139614+renovate[bot]@users.noreply.github.com"),
    ("Kiro", "kiro@example.com"),
    ("Kiro Tanaka", "kiro@example.com"),
    ("Cline", "cline@example.com"),
    ("Patsy Cline", "patsy@example.com"),
    ("Cody", "cody@example.com"),
    ("Cody Rhodes", "cody@example.com"),
    ("Junie", "junie@example.com"),
    ("Amp", "amp@example.com"),
    ("Trae", "trae@example.com"),
    ("Roo", "roo@example.com"),
    ("Opus", "opus@example.com"),
    ("Jane 2", "j@example.com"),
    ("Henry 8", "h@example.com"),
    ("Sam Kiro", "sam@kiro.dev"),
]


def who_env(author=None, committer=None):
    env = dict(os.environ)
    if author:
        env |= {"GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1]}
    if committer:
        env |= {"GIT_COMMITTER_NAME": committer[0], "GIT_COMMITTER_EMAIL": committer[1]}
    return env


def run(repo, *args, env=None, stdin=None):
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, input=stdin, capture_output=True, text=True, check=False
    )


def commit(repo, message="change", author=None, committer=None, extra=()):
    with (repo / "f.txt").open("a") as fh:
        fh.write("x\n")
    git(repo, "add", "f.txt")
    return run(
        repo, "commit", "-q", "-F", "-", *extra, stdin=message, env=who_env(author, committer)
    )


@pytest.fixture
def guarded(repo, mem, capsys):
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    capsys.readouterr()
    return repo


def test_a_real_commit_refuses_each_ai_author(guarded):
    wrong = [who for who in REFUSED if commit(guarded, author=who).returncode == 0]
    assert wrong == []


def test_a_real_commit_refuses_each_ai_committer(guarded):
    wrong = [who for who in REFUSED if commit(guarded, committer=who).returncode == 0]
    assert wrong == []


def test_a_real_commit_allows_each_human_and_plain_bot(guarded):
    wrong = [
        (who, result.stderr)
        for who in ALLOWED
        if (result := commit(guarded, author=who, committer=who)).returncode != 0
    ]
    assert wrong == []


def test_a_refusal_names_the_identity_and_the_fix(guarded):
    result = commit(guarded, author=("Cursor Agent", "cursoragent@cursor.com"))
    assert result.returncode != 0
    assert "Cursor Agent <cursoragent@cursor.com>" in result.stderr
    assert "--reset-author" in result.stderr
    assert "--no-verify" not in result.stderr


def test_an_amend_keeps_the_ai_author_so_it_is_refused_until_reset(repo, mem, capsys):
    ai = ("Cursor Agent", "cursoragent@cursor.com")
    assert commit(repo, author=ai).returncode == 0
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    assert run(repo, "commit", "--amend", "-q", "-m", "changed").returncode != 0
    assert run(repo, "commit", "--amend", "-q", "--reset-author", "-m", "changed").returncode == 0
    assert git(repo, "log", "-1", "--format=%an").strip() == "Test"


def test_an_amend_to_an_ai_author_is_refused(guarded):
    assert commit(guarded).returncode == 0
    bad = run(guarded, "commit", "--amend", "-q", "--no-edit", "--author=Claude Code <c@x.dev>")
    assert bad.returncode != 0
    assert run(guarded, "commit", "--amend", "-q", "--no-edit").returncode == 0


@pytest.mark.parametrize(
    "line",
    [
        "Made-with: Cursor",
        "Made with Cursor",
        "Co-authored-by: Cursor <cursoragent@cursor.com>",
        "Generated with Claude Code",
    ],
)
def test_the_lines_that_tools_add_are_refused_with_the_setting_to_turn_off(guarded, line):
    result = commit(guarded, f"Fix bug\n\n{line}\n")
    assert result.returncode != 0
    assert line in result.stderr
    assert '"attribution": {"commit": ""} in ~/.claude/settings.json' in result.stderr
    assert '"attributeCommitsToAgent": false} in ~/.cursor/cli-config.json' in result.stderr


@pytest.mark.parametrize(
    "line",
    [
        "Co-authored-by: Opus 4.7",
        "Opus 4.7",
        "Claude Sonnet 4.6.",
        "GPT-5.5",
        "Co-authored-by: Opus 4.7 <jane@example.com>",
        "Co-authored-by: Sonnet 4.6",
        "Co-authored-by: A New Tool 4.7",
        "Co-authored-by: A New Tool 4.7 <jane@example.com>",
        "Co-authored-by: o3-mini",
        "Co-authored-by: Gemini 3 Pro",
        "Co-authored-by: Kimi K2",
        "Co-authored-by: GLM-5",
        "Co-authored-by: Qwen3 <q@example.com>",
        "Co-authored-by: Kiro",
        "Co-authored-by: Kiro <noreply@kiro.dev>",
        "Generated-with: Kiro",
        "Generated-with: Cline",
        "Generated with Cline",
        "Generated by Qoder",
        "Made with Qoder",
        "Made-with: Qoder",
        "Co-authored-by: Qoder <qoder@example.com>",
        "Co-authored-by: Cline <cline@cline.bot>",
        "Assisted-by: Cline:claude-sonnet-4-6",
        "Assisted-by: A New Tool:gpt-5.5",
        "Co-authored-by: Roo Code <noreply@roocode.com>",
        "Co-authored-by: Amp <amp@ampcode.com>",
        "Co-authored-by: Junie <junie@jetbrains.com>",
        "Co-authored-by: Zencoder <z@zencoder.ai>",
        "Co-authored-by: Kilo Code <noreply@kilocode.ai>",
        "Co-authored-by: Trae <noreply@trae.ai>",
        "Co-authored-by: Augment Code <auggie@augmentcode.com>",
        "Co-authored-by: Cody <cody@sourcegraph.com>",
        "Co-authored-by: Warp <agent@warp.dev>",
        "Co-authored-by: Any Name <noreply@newtool.ai>",
        "Co-authored-by: some-agent[bot] <1+some-agent[bot]@users.noreply.github.com>",
        "Co-authored-by: helper-ai[bot] <1+helper-ai[bot]@users.noreply.github.com>",
    ],
)
def test_current_tools_and_models_are_refused_by_shape(guarded, line):
    assert commit(guarded, f"Fix bug\n\n{line}\n").returncode != 0


@pytest.mark.parametrize(
    "line",
    [
        "Co-authored-by: Kiro Tanaka <kiro@example.com>",
        "Co-authored-by: Kiro <kiro@example.com>",
        "Co-authored-by: Patsy Cline <patsy@example.com>",
        "Co-authored-by: Cline <cline@example.com>",
        "Co-authored-by: Cody Rhodes <c@example.com>",
        "Co-authored-by: Cody <c@example.com>",
        "Co-authored-by: Junie Moon <j@example.com>",
        "Co-authored-by: Amp Smith <a@example.com>",
        "Co-authored-by: Henry 8 <h@example.com>",
        "Co-authored-by: Elizabeth II <e@example.com>",
        "Co-authored-by: Sam Lee 3rd <s@example.com>",
        "Co-authored-by: dependabot[bot] <1+dependabot[bot]@users.noreply.github.com>",
        "Signed-off-by: Jane Doe <j@example.com>",
        "Upgrade Opus to 4.7",
        "Bump GPT-4 client",
        "Generated by make",
        "Generated-by: gcc 13.2",
    ],
)
def test_human_names_and_ordinary_lines_pass(guarded, line):
    result = commit(guarded, f"Fix bug\n\n{line}\n")
    assert result.returncode == 0, result.stderr


def test_made_with_something_else_is_fine(guarded):
    assert commit(guarded, "Fix bug\n\nMade with care in the old module.\n").returncode == 0


def test_no_rule_means_no_identity_check(repo, mem, capsys):
    assert main(HOOK) == 0
    assert commit(repo, author=("Cursor Agent", "cursoragent@cursor.com")).returncode == 0


def test_identity_patterns_come_from_config(repo, mem, capsys):
    cfg = mem / "config.toml"
    cfg.write_text(cfg.read_text() + '\n[commit_msg_guard]\nidentity_patterns = ["^Robot Rob <"]\n')
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    assert commit(repo, author=("Robot Rob", "r@example.com")).returncode != 0
    assert commit(repo, author=("Cursor", "jane@example.com")).returncode == 0


def test_the_guard_writes_no_tracked_file(guarded):
    assert commit(guarded).returncode == 0
    assert git(guarded, "status", "--porcelain").strip() == ""
    assert "cairnkit" not in git(guarded, "ls-files")


def test_the_guard_chains_with_a_foreign_commit_msg_hook(repo, mem, capsys):
    path = repo / ".git" / "hooks" / "commit-msg"
    path.write_text('#!/bin/sh\necho team-check "$1" > team.log\n')
    path.chmod(0o755)
    (repo / ".git" / "info" / "exclude").write_text("team.log\n")
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    assert commit(repo, author=("Cursor Agent", "c@example.com")).returncode != 0
    assert not (repo / "team.log").exists()
    assert commit(repo).returncode == 0
    assert "team-check" in (repo / "team.log").read_text()


def tree_commit(repo, message="skipped the hook", author=None, committer=None, parent="HEAD"):
    """A commit that never ran commit-msg, as a rebase or a tool's plumbing can make."""
    env = who_env(author, committer)
    tree = git(repo, "rev-parse", f"{parent}^{{tree}}").strip()
    sha = run(repo, "commit-tree", tree, "-p", parent, "-m", message, env=env).stdout.strip()
    git(repo, "update-ref", "HEAD", sha)
    return sha


@pytest.fixture
def remote(guarded, tmp_path):
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    git(guarded, "remote", "add", "origin", str(tmp_path / "remote.git"))
    assert run(guarded, "push", "-q", "origin", "main").returncode == 0
    return tmp_path / "remote.git"


def remote_head(remote, ref="refs/heads/main"):
    return run(remote, "rev-parse", "--verify", "-q", ref).stdout.strip()


AI = ("Cursor Agent", "cursoragent@cursor.com")


@pytest.mark.parametrize(
    "made",
    [
        {"author": AI},
        {"committer": AI},
        {"message": "Fix\n\nCo-authored-by: Claude <noreply@anthropic.com>"},
    ],
    ids=["author", "committer", "trailer"],
)
def test_a_push_refuses_a_commit_that_skipped_the_hook(guarded, remote, made):
    before = remote_head(remote)
    sha = tree_commit(guarded, **made)
    result = run(guarded, "push", "origin", "main")
    assert result.returncode != 0
    assert "refused" in result.stderr
    assert "--no-verify" not in result.stderr
    assert remote_head(remote) == before
    assert remote_head(remote) != sha


@pytest.mark.parametrize(
    "made",
    [
        {"message": "Fix\n\nCo-authored-by: Opus 4.7"},
        {"author": ("Opus 4.7", "jane@example.com")},
        {"committer": ("Opus 4.7", "jane@example.com")},
        {"message": "Fix\n\nGenerated-with: Kiro"},
    ],
    ids=["trailer", "author", "committer", "kiro"],
)
def test_a_push_refuses_a_versioned_model_by_each_path(guarded, remote, made):
    tree_commit(guarded, **made)
    assert run(guarded, "push", "origin", "main").returncode != 0


def test_a_refused_push_names_the_commit(guarded, remote):
    sha = tree_commit(guarded, author=AI)
    result = run(guarded, "push", "origin", "main")
    assert "Cursor Agent <cursoragent@cursor.com>" in result.stderr
    assert sha[:7] in result.stderr


def test_a_push_of_human_commits_passes(guarded, remote):
    sha = tree_commit(guarded, author=("Cursor Smith", "cursor.smith@example.com"))
    assert run(guarded, "push", "-q", "origin", "main").returncode == 0
    assert remote_head(remote) == sha


def test_a_commit_already_on_a_remote_does_not_stop_later_pushes(guarded, remote, tmp_path):
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", "-b", "main", str(remote), str(other))
    git(other, "config", "user.name", "Teammate")
    git(other, "config", "user.email", "t@example.com")
    (other / "t.txt").write_text("t\n")
    git(other, "add", "t.txt")
    run(other, "commit", "-q", "-m", "from a teammate's tool", env=who_env(AI))
    git(other, "push", "-q", "origin", "main")
    git(guarded, "pull", "-q", "origin", "main")
    sha = tree_commit(guarded)
    result = run(guarded, "push", "-q", "origin", "main")
    assert result.returncode == 0, result.stderr
    assert remote_head(remote) == sha


def test_a_push_to_a_plain_url_checks_only_the_new_commits(repo, mem, capsys, tmp_path):
    ai_old = commit(repo, author=AI)
    assert ai_old.returncode == 0
    git(tmp_path, "init", "-q", "--bare", "url.git")
    url = str(tmp_path / "url.git")
    assert run(repo, "push", "-q", url, "main").returncode == 0
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    sha = tree_commit(repo)
    result = run(repo, "push", "-q", url, "main")
    assert result.returncode == 0, result.stderr
    assert remote_head(tmp_path / "url.git") == sha


def test_deleting_a_branch_and_pushing_a_tag_pass(guarded, remote):
    git(guarded, "branch", "topic")
    assert run(guarded, "push", "-q", "origin", "topic").returncode == 0
    assert run(guarded, "push", "-q", "origin", ":topic").returncode == 0
    git(guarded, "tag", "-a", "v1", "-m", "one")
    assert run(guarded, "push", "-q", "origin", "v1").returncode == 0


@pytest.mark.parametrize("shell", ["sh", "bash", "zsh", "dash"])
def test_a_foreign_pre_push_hook_still_reads_the_ref_list(repo, mem, capsys, tmp_path, shell):
    found = shutil.which(shell)
    if found is None:
        pytest.skip(f"no {shell} here")
    path = repo / ".git" / "hooks" / "pre-push"
    log = tmp_path / "refs.log"
    path.write_text(f"#!{found}\ncat > {log}\n")
    path.chmod(0o755)
    assert main(ADD_RULE) == 0
    assert main(HOOK) == 0
    git(tmp_path, "init", "-q", "--bare", "r.git")
    git(repo, "remote", "add", "origin", str(tmp_path / "r.git"))
    result = run(repo, "push", "-q", "origin", "main")
    assert result.returncode == 0, result.stderr
    head = git(repo, "rev-parse", "HEAD").strip()
    assert log.read_text() == f"refs/heads/main {head} refs/heads/main {'0' * 40}\n"


def test_no_rule_means_the_push_is_not_checked(repo, mem, capsys, tmp_path):
    assert main(HOOK) == 0
    git(tmp_path, "init", "-q", "--bare", "r.git")
    git(repo, "remote", "add", "origin", str(tmp_path / "r.git"))
    tree_commit(repo, author=AI)
    assert run(repo, "push", "-q", "origin", "main").returncode == 0


def test_a_rule_added_later_turns_the_push_check_on(repo, mem, capsys, tmp_path):
    assert main(HOOK) == 0
    assert main(ADD_RULE) == 0
    git(tmp_path, "init", "-q", "--bare", "r.git")
    git(repo, "remote", "add", "origin", str(tmp_path / "r.git"))
    tree_commit(repo, author=AI)
    assert run(repo, "push", "-q", "origin", "main").returncode != 0


def test_the_push_check_goes_when_the_rule_ends(repo, mem, capsys, tmp_path):
    capsys.readouterr()
    assert main(ADD_RULE) == 0
    fact = capsys.readouterr().out.strip().split()[-1]
    assert main(HOOK) == 0
    assert main(["change", fact, "--status", "expired", "--reason", "Not needed."]) == 0
    assert main(HOOK) == 0
    git(tmp_path, "init", "-q", "--bare", "r.git")
    git(repo, "remote", "add", "origin", str(tmp_path / "r.git"))
    tree_commit(repo, author=AI)
    assert run(repo, "push", "-q", "origin", "main").returncode == 0


def test_refresh_keeps_both_checks(guarded, remote):
    assert main(["init", "--refresh"]) == 0
    assert commit(guarded, author=AI).returncode != 0
    git(guarded, "reset", "-q")
    tree_commit(guarded, author=AI)
    assert run(guarded, "push", "origin", "main").returncode != 0
