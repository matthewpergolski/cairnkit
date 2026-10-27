"""Personal pre-push and post-merge hooks from `memory hooks install`.

These hooks are not shared. `memory init` does not write them.
"""

from conftest import git

from cairnkit import githook
from cairnkit.cli import main


def install(capsys, *args):
    capsys.readouterr()
    code = main(["hooks", "install", *args])
    return code, capsys.readouterr().out


def hook(repo, name):
    return repo / ".git" / "hooks" / name


def test_init_does_not_write_the_tidy_hooks_and_hints_to_install(repo, capsys):
    capsys.readouterr()
    assert main(["init", "--no-default-rules"]) == 0
    out = capsys.readouterr().out
    assert "memory hooks install" in out
    assert not hook(repo, "pre-push").exists()
    assert not hook(repo, "post-merge").exists()


def test_install_writes_both_hooks_and_a_second_run_keeps_one_block(repo, mem, capsys):
    code, _ = install(capsys, "--agent", "generic")
    assert code == 0
    for name in ("pre-push", "post-merge"):
        path = hook(repo, name)
        assert path.is_file() and path.stat().st_mode & 0o111
        text = path.read_text()
        assert f"hook {name}" in text and "|| true" in text
        assert text.count(githook.START) == 1 and text.count(githook.END) == 1
    install(capsys, "--agent", "generic")
    for name in ("pre-push", "post-merge"):
        text = hook(repo, name).read_text()
        assert text.count(githook.START) == 1 and text.count(githook.END) == 1


def test_uninstall_removes_only_our_block_and_keeps_a_foreign_hook(repo, mem, capsys):
    for name, line in (("pre-push", "echo team-push"), ("post-merge", "echo team-merge")):
        path = hook(repo, name)
        path.write_text(f"#!/bin/sh\n{line}\nexit 0\n")
        path.chmod(0o755)
    install(capsys, "--agent", "generic")
    install(capsys, "--agent", "generic")
    for name, line in (("pre-push", "echo team-push"), ("post-merge", "echo team-merge")):
        text = hook(repo, name).read_text()
        assert text.count(githook.START) == 1
        assert line in text and text.index("cairnkit") < text.index(line)
    assert main(["hooks", "uninstall"]) == 0
    for name, line in (("pre-push", "echo team-push"), ("post-merge", "echo team-merge")):
        assert hook(repo, name).read_text() == f"#!/bin/sh\n{line}\nexit 0\n"


def test_dry_run_prints_would_write_and_writes_nothing(repo, mem, capsys):
    code, out = install(capsys, "--agent", "generic", "--dry-run")
    assert code == 0
    assert "would write" in out and "pre-push" in out and "post-merge" in out
    assert not hook(repo, "pre-push").exists()
    assert not hook(repo, "post-merge").exists()
    assert not (repo / ".githooks").exists()


def test_uninstall_dry_run_leaves_the_hooks(repo, mem, capsys):
    install(capsys, "--agent", "generic")
    before = {name: hook(repo, name).read_text() for name in ("pre-push", "post-merge")}
    capsys.readouterr()
    assert main(["hooks", "uninstall", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would update" in out and "pre-push" in out and "post-merge" in out
    for name, text in before.items():
        assert hook(repo, name).read_text() == text


def test_no_git_hook_skips_the_tidy_hooks(repo, mem, capsys):
    code, _ = install(capsys, "--agent", "generic", "--no-git-hook")
    assert code == 0
    for name in ("pre-commit", "post-checkout", "pre-push", "post-merge"):
        assert not hook(repo, name).exists()


def test_hooks_path_inside_the_repo_prints_the_block_and_writes_nothing(repo, mem, capsys):
    (repo / ".githooks").mkdir()
    git(repo, "config", "core.hooksPath", ".githooks")
    code, out = install(capsys, "--agent", "generic")
    assert code == 0
    for name in ("pre-push", "post-merge"):
        assert f"skip {name}" in out and "by hand" in out
        assert not (repo / ".githooks" / name).exists()
        assert not hook(repo, name).exists()


def test_shared_mode_does_not_add_the_tidy_hooks_to_the_tracked_dir(repo, mem, capsys):
    code, _ = install(capsys, "--agent", "generic", "--commit-msg-guard=shared")
    assert code == 0
    assert (repo / ".githooks" / "pre-commit").is_file()
    assert not (repo / ".githooks" / "pre-push").exists()
    assert not (repo / ".githooks" / "post-merge").exists()
    assert hook(repo, "pre-push").is_file() and hook(repo, "post-merge").is_file()


def test_a_tracked_agent_hook_file_is_left_alone_and_not_excluded(repo, mem, capsys):
    path = repo / ".cursor" / "hooks.json"
    path.parent.mkdir()
    original = '{"version": 1, "hooks": {}}\n'
    path.write_text(original)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "team hooks")
    exclude = repo / ".git" / "info" / "exclude"
    before = exclude.read_text()
    code, out = install(capsys, "--agent", "cursor")
    assert code == 0
    assert "tracked" in out and "hook session-start" in out and "hook stop" in out
    assert path.read_text() == original
    assert exclude.read_text() == before
    assert ".cursor/hooks.json" not in exclude.read_text().splitlines()
    assert git(repo, "status", "--porcelain") == ""


def test_refresh_rewrites_a_tidy_hook_once_and_does_not_add_the_other(repo, mem, capsys):
    path = hook(repo, "pre-push")
    path.write_text(f"#!/bin/sh\n{githook.START}\nold body\n{githook.END}\necho mine\n")
    assert main(["init", "--refresh"]) == 0
    text = path.read_text()
    assert text.count(githook.START) == 1 and text.count(githook.END) == 1
    assert "hook pre-push" in text and "old body" not in text
    assert text.endswith("echo mine\n")
    assert not hook(repo, "post-merge").exists()
    assert main(["init", "--refresh"]) == 0
    assert path.read_text() == text
