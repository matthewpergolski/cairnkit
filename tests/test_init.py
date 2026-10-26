import os
from pathlib import Path

from conftest import add_worktree, git

from cairnkit.cli import main


def sibling(repo: Path) -> Path:
    return repo.parent / "proj.memory"


def test_init_creates_skeleton_and_relative_link(repo):
    assert main(["init"]) == 0
    mem = sibling(repo)
    for part in ("facts", "notes", "branches"):
        assert (mem / part).is_dir()
    assert (mem / "config.toml").is_file()
    assert (mem / "README.md").is_file()
    assert (mem / "notes" / "status.md").is_file()
    link = repo / "memory-bank"
    assert link.is_symlink()
    assert not os.path.isabs(os.readlink(link))
    assert link.resolve() == mem.resolve()


def test_init_uses_info_exclude_by_default(repo):
    before = (repo / ".gitignore").read_text()
    assert main(["init"]) == 0
    assert (repo / ".gitignore").read_text() == before
    exclude = (repo / ".git" / "info" / "exclude").read_text().splitlines()
    assert "memory-bank" in exclude and ".memory-path" in exclude
    git(repo, "check-ignore", "-q", "memory-bank")
    assert git(repo, "status", "--porcelain") == ""


def test_init_adds_gitignore_lines_once(repo):
    assert main(["init", "--gitignore"]) == 0
    assert main(["init", "--gitignore"]) == 0
    lines = (repo / ".gitignore").read_text().splitlines()
    assert lines.count("memory-bank") == 1
    assert lines.count(".memory-path") == 1
    assert ".worktrees/" in lines


def test_trailing_slash_entry_is_not_enough(repo):
    (repo / ".gitignore").write_text("memory-bank/\n")
    assert main(["init", "--gitignore"]) == 0
    assert "memory-bank" in (repo / ".gitignore").read_text().splitlines()


def test_git_never_stages_the_link(repo):
    assert main(["init"]) == 0
    git(repo, "add", "-A")
    staged = git(repo, "diff", "--cached", "--name-only").split()
    assert "memory-bank" not in staged
    assert all(not name.startswith("memory-bank") for name in staged)
    git(repo, "check-ignore", "-q", "memory-bank")


def test_refuses_real_folder_with_files(repo, capsys):
    real = repo / "memory-bank"
    real.mkdir()
    (real / "notes.md").write_text("old notes\n")
    assert main(["init"]) != 0
    err = capsys.readouterr().err
    assert "migrate" in err
    assert "notes.md" in err
    assert real.is_dir() and not real.is_symlink()
    assert not sibling(repo).exists()


def test_empty_real_folder_is_replaced(repo):
    (repo / "memory-bank").mkdir()
    assert main(["init"]) == 0
    assert (repo / "memory-bank").is_symlink()


def test_dry_run_changes_nothing(repo, capsys):
    before = (repo / ".gitignore").read_text()
    assert main(["init", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "dry run" in out.lower()
    assert not sibling(repo).exists()
    assert not (repo / "memory-bank").exists()
    assert (repo / ".gitignore").read_text() == before


def test_path_flag_writes_memory_path_file(repo, tmp_path):
    target = tmp_path / "elsewhere" / "mem"
    assert main(["init", "--path", str(target)]) == 0
    assert (target / "facts").is_dir()
    assert (repo / "memory-bank").resolve() == target.resolve()
    stored = (repo / ".memory-path").read_text().splitlines()[0]
    assert (repo / stored).resolve() == target.resolve()
    # A second run with no flag finds the same place through .memory-path.
    assert main(["init"]) == 0
    assert (repo / "memory-bank").resolve() == target.resolve()
    assert not sibling(repo).exists()


def test_env_var_sets_location(repo, tmp_path, monkeypatch):
    target = tmp_path / "from-env"
    monkeypatch.setenv("MEMORY_DIR", str(target))
    assert main(["init"]) == 0
    assert (repo / "memory-bank").resolve() == target.resolve()


def test_relinks_when_link_points_elsewhere(repo, tmp_path):
    (repo / "memory-bank").symlink_to(tmp_path / "old-place")
    assert main(["init"]) == 0
    assert (repo / "memory-bank").resolve() == sibling(repo).resolve()


def test_links_every_worktree_to_one_folder(repo):
    wt = add_worktree(repo, "feature-x")
    assert main(["init"]) == 0
    mem = sibling(repo).resolve()
    assert (repo / "memory-bank").resolve() == mem
    assert (wt / "memory-bank").resolve() == mem
    assert not os.path.isabs(os.readlink(wt / "memory-bank"))
    git(wt, "check-ignore", "-q", "memory-bank")


def test_init_from_inside_a_worktree_uses_main_checkout_sibling(repo, monkeypatch):
    wt = add_worktree(repo, "feature-y")
    monkeypatch.chdir(wt)
    assert main(["init"]) == 0
    mem = sibling(repo).resolve()
    assert (wt / "memory-bank").resolve() == mem
    assert (repo / "memory-bank").resolve() == mem
    assert not (wt.parent / "feature-y.memory").exists()


def test_existing_memory_data_is_kept(repo):
    assert main(["init"]) == 0
    fact_file = sibling(repo) / "facts" / "main.jsonl"
    fact_file.write_text('{"keep": true}\n')
    (sibling(repo) / "notes" / "status.md").write_text("my status\n")
    assert main(["init"]) == 0
    assert fact_file.read_text() == '{"keep": true}\n'
    assert (sibling(repo) / "notes" / "status.md").read_text() == "my status\n"


def test_init_outside_git_links_current_folder(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert main(["init"]) == 0
    assert (plain / "memory-bank").resolve() == (tmp_path / "plain.memory").resolve()
