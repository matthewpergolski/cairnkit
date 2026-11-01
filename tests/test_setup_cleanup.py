"""Setup survives one bad tool file. Uninstall takes back what it wrote, and only that."""

import json
import subprocess

from conftest import git

from cairnkit.cli import main

HEADER = "# Private project memory (a link to a folder outside the repo)"
ALL_TOOLS = ("claude", "codex", "cursor", "grok", "pi", "opencode")


def exclude_text(repo):
    return (repo / ".git" / "info" / "exclude").read_text()


def connect_all(repo):
    for name in ALL_TOOLS:
        (repo / f".{name}").mkdir(exist_ok=True)
    assert main(["hooks", "install"]) == 0


def test_the_exclude_header_is_written_once(repo, mem):
    connect_all(repo)
    assert main(["instructions", "--write-instructions"]) == 0
    assert exclude_text(repo).count(HEADER) == 1


def test_a_second_install_leaves_the_exclude_as_it_was(repo, mem):
    connect_all(repo)
    before = exclude_text(repo)
    connect_all(repo)
    assert exclude_text(repo) == before


def test_old_repeated_headers_collapse_and_other_lines_stay(repo, mem):
    path = repo / ".git" / "info" / "exclude"
    path.write_text(f"mine.log\n{HEADER}\nmemory-bank\n{HEADER}\n.memory-path\n# my note\n")
    connect_all(repo)
    text = path.read_text()
    assert text.count(HEADER) == 1
    for line in ("mine.log", "memory-bank", ".memory-path", "# my note"):
        assert line in text.splitlines()


def test_a_bad_tool_file_does_not_stop_the_other_setup(repo, mem, capsys):
    (repo / ".cursor").mkdir()
    bad = repo / ".cursor" / "hooks.json"
    bad.write_text("{bad")
    (repo / ".claude").mkdir()
    capsys.readouterr()
    assert main(["hooks", "install"]) == 0
    out = capsys.readouterr().out
    assert str(bad) in out and "memory hooks install" in out
    assert "Nothing changed" not in out
    assert bad.read_text() == "{bad"
    assert (repo / ".claude" / "settings.local.json").is_file()
    assert (repo / ".git" / "hooks" / "pre-commit").is_file()


def test_init_with_a_bad_tool_file_exits_zero_and_installs_git_hooks(repo, capsys, monkeypatch):
    from cairnkit import hooks_cmd

    monkeypatch.setattr(hooks_cmd, "INSTALL_ON_INIT", True)
    (repo / ".cursor").mkdir()
    (repo / ".cursor" / "hooks.json").write_text("{bad")
    assert main(["init"]) == 0
    out = capsys.readouterr().out
    assert "hooks.json" in out
    assert "Git hooks installed" in out
    assert (repo / ".git" / "hooks" / "pre-commit").is_file()


def test_a_tool_file_with_the_wrong_shape_counts_as_bad(repo, mem, capsys):
    (repo / ".cursor").mkdir()
    bad = repo / ".cursor" / "hooks.json"
    bad.write_text(json.dumps({"hooks": {"stop": "not a list"}}))
    (repo / ".codex").mkdir()
    (repo / ".codex" / "hooks.json").write_text(json.dumps({"hooks": {"Stop": ["not a group"]}}))
    capsys.readouterr()
    assert main(["hooks", "install"]) == 0
    out = capsys.readouterr().out
    assert str(bad) in out and "Traceback" not in out
    assert (repo / ".git" / "hooks" / "pre-commit").is_file()


def test_a_tool_asked_for_by_name_with_a_bad_file_fails(repo, mem, capsys):
    (repo / ".cursor").mkdir()
    (repo / ".cursor" / "hooks.json").write_text("{bad")
    assert main(["hooks", "install", "--agent", "cursor"]) == 1
    assert (repo / ".git" / "hooks" / "pre-commit").is_file()


def test_a_bad_file_stays_out_of_the_seen_record_so_the_next_look_tries_it(repo, mem):
    (repo / ".cursor").mkdir()
    bad = repo / ".cursor" / "hooks.json"
    bad.write_text("{bad")
    assert main(["hooks", "install"]) == 0
    assert "cursor" not in json.loads((mem / ".agents-seen.json").read_text())


def test_uninstall_goes_on_past_a_bad_file_and_says_so(repo, mem, capsys):
    connect_all(repo)
    (repo / ".cursor" / "hooks.json").write_text("{bad")
    capsys.readouterr()
    assert main(["hooks", "uninstall"]) == 1
    out = capsys.readouterr().out
    assert "hooks.json" in out
    assert not (repo / ".claude" / "settings.local.json").exists()
    assert not (repo / ".git" / "hooks" / "pre-commit").exists()


def test_uninstall_removes_the_empty_tool_folders_it_left(repo, mem):
    connect_all(repo)
    assert main(["instructions", "--write-instructions"]) == 0
    assert main(["hooks", "uninstall"]) == 0
    left = {p.name for p in repo.iterdir()} - {".git", "memory-bank"}
    assert not {f".{name}" for name in ALL_TOOLS} & left
    assert "CLAUDE.local.md" not in left


def test_uninstall_keeps_a_file_of_the_developer_in_a_tool_folder(repo, mem):
    connect_all(repo)
    (repo / ".claude" / "mine.json").write_text("{}")
    (repo / ".pi" / "extensions" / "mine.ts").write_text("x")
    assert main(["hooks", "uninstall"]) == 0
    assert (repo / ".claude" / "mine.json").read_text() == "{}"
    assert (repo / ".pi" / "extensions" / "mine.ts").read_text() == "x"
    assert not (repo / ".pi" / "extensions" / "cairnkit.ts").exists()


def test_uninstall_keeps_an_empty_folder_that_it_wrote_nothing_in(repo, mem):
    (repo / ".claude").mkdir()
    assert main(["hooks", "uninstall"]) == 0
    assert (repo / ".claude").is_dir()


def test_uninstall_removes_the_rules_block_and_keeps_hand_written_text(repo, mem):
    local = repo / "CLAUDE.local.md"
    local.write_text("My own notes.\n")
    assert main(["instructions", "--write-instructions"]) == 0
    assert "cairnkit:start" in local.read_text()
    assert main(["hooks", "uninstall"]) == 0
    assert local.read_text().strip() == "My own notes."
    assert "CLAUDE.local.md" in exclude_text(repo).splitlines()


def test_uninstall_removes_a_block_file_that_holds_only_tool_text(repo, mem):
    (repo / "AGENTS.md").write_text("Team rules.\n")
    git(repo, "add", "AGENTS.md")
    git(repo, "commit", "-q", "-m", "docs")
    assert main(["instructions", "--write-instructions"]) == 0
    assert (repo / "CLAUDE.local.md").read_text().startswith("@AGENTS.md")
    assert main(["hooks", "uninstall"]) == 0
    assert not (repo / "CLAUDE.local.md").exists()
    assert not (repo / ".cursor" / "rules" / "cairnkit.mdc").exists()
    assert (repo / "AGENTS.md").read_text() == "Team rules.\n"


def test_uninstall_never_changes_a_tracked_file_with_a_block(repo, mem):
    tracked = repo / "CLAUDE.md"
    tracked.write_text(
        "Team.\n<!-- cairnkit:start -->\nold block\n<!-- cairnkit:end -->\n",
    )
    git(repo, "add", "CLAUDE.md")
    git(repo, "commit", "-q", "-m", "docs")
    before = tracked.read_text()
    assert main(["hooks", "uninstall"]) == 0
    assert tracked.read_text() == before


def test_uninstall_takes_back_its_exclude_lines_and_keeps_the_link_lines(repo, mem):
    connect_all(repo)
    path = repo / ".git" / "info" / "exclude"
    path.write_text(path.read_text() + "mine.log\n")
    assert main(["hooks", "uninstall"]) == 0
    lines = exclude_text(repo).splitlines()
    assert "memory-bank" in lines and ".memory-path" in lines and "mine.log" in lines
    assert ".claude/settings.local.json" not in lines
    assert ".pi/extensions/cairnkit.ts" not in lines


def test_uninstall_dry_run_changes_nothing(repo, mem):
    connect_all(repo)
    assert main(["instructions", "--write-instructions"]) == 0
    before = sorted(str(p) for p in repo.rglob("*") if ".git/" not in str(p))
    exclude = exclude_text(repo)
    assert main(["hooks", "uninstall", "--dry-run"]) == 0
    assert sorted(str(p) for p in repo.rglob("*") if ".git/" not in str(p)) == before
    assert exclude_text(repo) == exclude


def test_init_inside_a_bare_repo_refuses_and_writes_nothing(tmp_path, monkeypatch, capsys):
    bare = tmp_path / "b.git"
    bare.mkdir()
    git(bare, "init", "-q", "--bare")
    before = sorted(p.name for p in bare.iterdir())
    monkeypatch.chdir(bare)
    capsys.readouterr()
    assert main(["init"]) == 1
    out = capsys.readouterr()
    assert "Nothing changed" in out.err and "worktree" in out.err
    assert "nothing in git changes" not in out.out
    assert sorted(p.name for p in bare.iterdir()) == before
    assert not (tmp_path / "b.git.memory").exists()


def test_hooks_install_inside_a_git_folder_refuses(repo, mem, monkeypatch, capsys):
    monkeypatch.chdir(repo / ".git")
    before = sorted(p.name for p in (repo / ".git").iterdir())
    assert main(["hooks", "install"]) == 1
    assert sorted(p.name for p in (repo / ".git").iterdir()) == before


def test_init_in_a_real_repo_still_says_nothing_in_git_changes(repo, capsys):
    capsys.readouterr()
    assert main(["init"]) == 0
    assert "nothing in git changes" in capsys.readouterr().out
    status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True)
    assert status.stdout == b""
