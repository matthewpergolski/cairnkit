"""A worktree added after `memory init` gets its memory link with no help."""

import os
import subprocess
import sys

from conftest import git

from cairnkit.cli import main

ZERO = "0" * 40


def new_worktree(repo, branch, *extra):
    path = repo / ".worktrees" / branch
    return path, subprocess.run(
        ["git", "worktree", "add", "-b", branch, *extra, str(path)],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def install(capsys, *args):
    capsys.readouterr()
    cmd = ["hooks", "install", *args]
    if not any(a == "--agent" or str(a).startswith("--agent=") for a in args):
        cmd[2:2] = ["--agent", "generic"]
    assert main(cmd) == 0
    return capsys.readouterr().out


def run(capsys, *args):
    capsys.readouterr()
    code = main(list(args))
    return code, capsys.readouterr().out


# --- the post-checkout hook -------------------------------------------------


def test_worktree_add_links_the_new_worktree(repo, mem, capsys, monkeypatch):
    install(capsys)
    hook = repo / ".git" / "hooks" / "post-checkout"
    assert hook.is_file() and hook.stat().st_mode & 0o111
    wt, result = new_worktree(repo, "feature-a")
    assert result.returncode == 0, result.stderr
    link = wt / "memory-bank"
    assert link.is_symlink()
    assert not os.path.isabs(os.readlink(link))
    assert link.resolve() == mem.resolve()
    assert "linked" in result.stdout + result.stderr
    git(wt, "check-ignore", "-q", "memory-bank")
    assert git(wt, "status", "--porcelain") == ""
    monkeypatch.chdir(wt)
    code, out = run(capsys, "check")
    assert code == 0, out


def test_hook_skips_a_plain_checkout(repo, mem, capsys):
    install(capsys)
    wt, _ = new_worktree(repo, "feature-b")
    (wt / "memory-bank").unlink()
    git(wt, "checkout", "-q", "-b", "feature-b2")
    assert not os.path.lexists(wt / "memory-bank")


def test_hook_leaves_a_tracked_path_alone(repo, mem, capsys):
    install(capsys)
    git(repo, "checkout", "-q", "-b", "has-file")
    (repo / "memory-bank").unlink()
    (repo / "memory-bank").write_text("tracked\n")
    git(repo, "add", "-f", "memory-bank")
    git(repo, "commit", "-q", "--no-verify", "-m", "tracked file")
    git(repo, "checkout", "-q", "main")
    wt = repo / ".worktrees" / "tracked"
    result = subprocess.run(
        ["git", "worktree", "add", str(wt), "has-file"], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert not (wt / "memory-bank").is_symlink()
    assert (wt / "memory-bank").read_text() == "tracked\n"
    assert git(wt, "status", "--porcelain") == ""


def test_hook_with_no_memory_folder_does_nothing(repo, capsys):
    install(capsys)
    wt, result = new_worktree(repo, "feature-c")
    assert result.returncode == 0, result.stderr
    assert not os.path.lexists(wt / "memory-bank")


def test_hook_command_never_fails(repo, mem, capsys, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("cairnkit.hookrun.link_here", boom)
    code, _ = run(capsys, "hook", "post-checkout")
    assert code == 0


def test_uninstall_removes_the_post_checkout_hook(repo, mem, capsys):
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text("#!/bin/sh\necho team-hook\n")
    hook.chmod(0o755)
    install(capsys)
    assert "cairnkit" in hook.read_text()
    assert main(["hooks", "uninstall"]) == 0
    assert hook.read_text() == "#!/bin/sh\necho team-hook\n"


def test_no_git_hook_skips_post_checkout(repo, mem, capsys):
    install(capsys, "--no-git-hook")
    assert not (repo / ".git" / "hooks" / "post-checkout").exists()


def test_shared_hooks_link_new_worktrees_too(repo, mem, capsys):
    install(capsys, "--commit-msg-guard=shared")
    text = (repo / ".githooks" / "post-checkout").read_text()
    assert "memory hook post-checkout" in text
    assert "command -v memory" in text


def test_shared_hook_links_a_real_new_worktree(repo, mem, capsys, monkeypatch):
    # The shared hook runs `memory` from PATH: put this checkout's tool there.
    bin_dir = os.path.dirname(sys.executable)
    monkeypatch.setenv("PATH", bin_dir + os.pathsep + os.environ["PATH"])
    install(capsys, "--commit-msg-guard=shared")
    git(repo, "config", "core.hooksPath", ".githooks")
    git(repo, "add", ".githooks")
    git(repo, "commit", "-q", "-m", "shared hooks")
    wt, result = new_worktree(repo, "feature-shared")
    assert result.returncode == 0, result.stderr
    assert (wt / "memory-bank").resolve() == mem.resolve()
    git(wt, "check-ignore", "-q", "memory-bank")


# --- self-heal in load and check ---------------------------------------------


def unlinked_worktree(repo, branch, monkeypatch):
    wt, result = new_worktree(repo, branch)
    assert result.returncode == 0, result.stderr
    assert not os.path.lexists(wt / "memory-bank")
    monkeypatch.chdir(wt)
    return wt


def test_check_links_an_unlinked_worktree(repo, mem, capsys, monkeypatch):
    wt = unlinked_worktree(repo, "feature-d", monkeypatch)
    code, out = run(capsys, "check")
    assert code == 0, out
    assert (wt / "memory-bank").resolve() == mem.resolve()
    assert not os.path.isabs(os.readlink(wt / "memory-bank"))
    linked = [line for line in out.splitlines() if line.startswith("memory: linked")]
    assert len(linked) == 1
    git(wt, "check-ignore", "-q", "memory-bank")
    code, out = run(capsys, "check")
    assert "memory: linked" not in out


def test_load_links_an_unlinked_worktree(repo, mem, capsys, monkeypatch):
    wt = unlinked_worktree(repo, "feature-e", monkeypatch)
    code, out = run(capsys, "load")
    assert code == 0
    assert (wt / "memory-bank").resolve() == mem.resolve()
    assert "linked" in out
    assert "# Project memory" in out


def test_self_heal_restores_a_lost_exclude_line(repo, mem, capsys, monkeypatch):
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text("")
    wt = unlinked_worktree(repo, "feature-f", monkeypatch)
    run(capsys, "load")
    git(wt, "check-ignore", "-q", "memory-bank")
    assert git(wt, "status", "--porcelain") == ""


def test_no_link_when_the_ignore_line_cannot_be_written(repo, mem, capsys, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr("cairnkit.init.exclude", fail)
    wt = unlinked_worktree(repo, "feature-ro", monkeypatch)
    code, _ = run(capsys, "load")
    assert code == 0
    assert not os.path.lexists(wt / "memory-bank")


def test_no_memory_folder_no_link(repo, capsys, monkeypatch):
    wt = unlinked_worktree(repo, "feature-g", monkeypatch)
    run(capsys, "load")
    run(capsys, "check")
    assert not os.path.lexists(wt / "memory-bank")


def test_real_folder_is_never_replaced(repo, mem, capsys, monkeypatch):
    wt = unlinked_worktree(repo, "feature-h", monkeypatch)
    (wt / "memory-bank").mkdir()
    (wt / "memory-bank" / "x.md").write_text("x")
    code, out = run(capsys, "check")
    assert code == 1
    assert (wt / "memory-bank" / "x.md").read_text() == "x"
    assert "real folder" in out
    assert "notes/" in out and "memory init" in out


def test_file_is_never_replaced(repo, mem, capsys, monkeypatch):
    wt = unlinked_worktree(repo, "feature-i", monkeypatch)
    (wt / "memory-bank").write_text("mine\n")
    code, out = run(capsys, "check")
    assert code == 1
    assert (wt / "memory-bank").read_text() == "mine\n"
    assert "a file, not a link" in out
    assert "memory init" in out


def test_link_elsewhere_is_never_replaced(repo, mem, capsys, tmp_path, monkeypatch):
    other = tmp_path / "other"
    other.mkdir()
    wt = unlinked_worktree(repo, "feature-j", monkeypatch)
    (wt / "memory-bank").symlink_to(other)
    code, out = run(capsys, "check")
    assert code == 1
    assert (wt / "memory-bank").resolve() == other.resolve()
    assert "points to" in out and "memory init" in out
    run(capsys, "load")
    assert (wt / "memory-bank").resolve() == other.resolve()


def test_main_checkout_is_healed_when_memory_exists(repo, mem, capsys):
    (repo / "memory-bank").unlink()
    code, out = run(capsys, "check")
    assert code == 0, out
    assert (repo / "memory-bank").resolve() == mem.resolve()
    assert "linked" in out


def test_hooks_install_links_worktrees_made_before_install(repo, mem, capsys, monkeypatch):
    """Older worktrees (no post-checkout yet) must get a link before agent config."""
    from conftest import add_worktree

    wt1 = add_worktree(repo, "old1")
    wt2 = add_worktree(repo, "old2")
    assert not os.path.lexists(wt1 / "memory-bank")
    assert not os.path.lexists(wt2 / "memory-bank")
    install(capsys, "--agent", "claude")
    assert (wt1 / "memory-bank").resolve() == mem.resolve()
    assert (wt2 / "memory-bank").resolve() == mem.resolve()
    assert (wt1 / ".claude" / "settings.local.json").is_file()
    assert (wt2 / ".claude" / "settings.local.json").is_file()
    git(wt1, "check-ignore", "-q", "memory-bank")
    assert git(wt1, "status", "--porcelain") == ""
    monkeypatch.chdir(wt1)
    code, out = run(capsys, "check", "--strict")
    assert code == 0, out


def test_check_heals_every_unlinked_worktree_not_only_cwd(repo, mem, capsys):
    from conftest import add_worktree

    wt1 = add_worktree(repo, "twin-a")
    wt2 = add_worktree(repo, "twin-b")
    code, out = run(capsys, "check")
    assert code == 0, out
    assert (wt1 / "memory-bank").resolve() == mem.resolve()
    assert (wt2 / "memory-bank").resolve() == mem.resolve()
    assert out.count("memory: linked") == 2


def test_missing_link_error_names_existing_memory_not_bare_init(
    repo, mem, capsys, monkeypatch
):
    """When a link cannot be auto-created, name the memory and the repair command."""

    def fail(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr("cairnkit.init.exclude", fail)
    from conftest import add_worktree

    wt = add_worktree(repo, "noheal")
    code, out = run(capsys, "check")
    assert code == 1
    assert not os.path.lexists(wt / "memory-bank")
    assert str(mem) in out
    assert f"memory init --path {mem}" in out
    assert "missing; run `memory init`" not in out


def test_no_memory_means_no_links_and_no_agent_config_in_worktrees(repo, capsys):
    from conftest import add_worktree

    wt = add_worktree(repo, "lonely")
    install(capsys, "--agent", "claude")
    assert not os.path.lexists(repo / "memory-bank")
    assert not os.path.lexists(wt / "memory-bank")
    # No memory to link to: do not write stop-hook config into an unlinked worktree.
    assert not (wt / ".claude" / "settings.local.json").exists()
