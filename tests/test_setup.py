"""Setup is one step, and it writes nothing that git tracks."""

from __future__ import annotations

import json

import pytest
from conftest import git

from cairnkit import adapters, hooks_cmd, refresh
from cairnkit.cli import main
from cairnkit.instructions import END, START
from cairnkit.paths import find_project


@pytest.fixture
def real_setup(repo, monkeypatch):
    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    monkeypatch.setattr(adapters, "detect", lambda project: ["claude", "codex", "cursor"])
    return repo


def test_init_connects_the_agents_and_git_in_one_step(real_setup):
    assert main(["init"]) == 0
    repo = real_setup
    assert (repo / ".git" / "hooks" / "pre-commit").is_file()
    assert (repo / ".git" / "hooks" / "post-merge").is_file()
    assert not (repo / ".git" / "hooks" / "post-commit").exists()
    assert (
        "SessionStart"
        in json.loads((repo / ".claude" / "settings.local.json").read_text())["hooks"]
    )
    assert "SessionStart" in json.loads((repo / ".codex" / "hooks.json").read_text())["hooks"]
    assert "sessionStart" in json.loads((repo / ".cursor" / "hooks.json").read_text())["hooks"]


def test_setup_leaves_git_status_clean(real_setup):
    assert main(["init"]) == 0
    assert git(real_setup, "status", "--porcelain") == ""


def test_setup_output_is_short(real_setup, capsys):
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert len(out.splitlines()) <= 5
    assert "Memory ready" in out
    assert "claude, codex, cursor" in out


def test_verbose_prints_each_step(real_setup, capsys):
    assert main(["init", "--verbose"]) == 0
    assert "create link" in capsys.readouterr().out


def test_no_hooks_skips_the_hooks(real_setup):
    assert main(["init", "--no-hooks"]) == 0
    assert not (real_setup / ".git" / "hooks" / "pre-commit").exists()


def test_a_second_setup_changes_nothing(real_setup, capsys):
    assert main(["init"]) == 0
    capsys.readouterr()
    before = git(real_setup, "status", "--porcelain")
    assert main(["init"]) == 0
    assert "already set up" in capsys.readouterr().out
    assert git(real_setup, "status", "--porcelain") == before


def test_a_rule_against_attribution_gets_its_check(real_setup):
    assert main(["init", "--preset", "commits"]) == 0
    assert (real_setup / ".git" / "hooks" / "commit-msg").is_file()


def test_no_rule_means_no_commit_message_check(real_setup):
    assert main(["init"]) == 0
    assert not (real_setup / ".git" / "hooks" / "commit-msg").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["init", "--gitignore"],
        ["hooks", "install", "--commit-msg-guard=shared"],
        ["migrate", "--fix-references"],
    ],
)
def test_options_that_wrote_tracked_files_are_gone(repo, argv):
    with pytest.raises(SystemExit):
        main(argv)


def test_write_instructions_leaves_a_tracked_agents_file_alone(repo, capsys):
    (repo / "AGENTS.md").write_text("Hand-written.\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-qm", "docs")
    assert main(["init", "--write-instructions", "--no-hooks"]) == 0
    assert (repo / "AGENTS.md").read_text() == "Hand-written.\n"
    assert git(repo, "status", "--porcelain") == ""


@pytest.mark.parametrize("name", ["CLAUDE.md", "AGENTS.md"])
@pytest.mark.parametrize("argv", [["init", "--refresh"], ["instructions", "--write-instructions"]])
def test_an_old_block_in_a_tracked_file_stays_and_the_rules_go_local(repo, capsys, name, argv):
    assert main(["init", "--no-hooks"]) == 0
    tracked = repo / name
    body = f"# Team\n\n{START}\nold rules\n{END}\n\nMore.\n"
    tracked.write_text(body)
    git(repo, "add", name)
    git(repo, "commit", "-qm", "rules")
    capsys.readouterr()
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert tracked.read_text() == body
    assert git(repo, "status", "--porcelain") == ""
    assert START in (repo / "CLAUDE.local.md").read_text()
    assert f"tracked {name} holds an old cairnkit block" in out


def test_refresh_does_not_keep_asking_about_a_tracked_block(repo):
    assert main(["init", "--no-hooks"]) == 0
    (repo / "CLAUDE.md").write_text(f"{START}\nold\n{END}\n")
    git(repo, "add", "CLAUDE.md")
    git(repo, "commit", "-qm", "rules")
    assert main(["init", "--refresh"]) == 0
    assert refresh.repo_line(find_project(), None) is None
