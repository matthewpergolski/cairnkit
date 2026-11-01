"""All worktrees of one bare repo, or of one submodule, share one memory."""

import pytest
from conftest import git

from cairnkit.cli import main
from cairnkit.paths import find_project, resolve_memory_dir


def worktrees_of_a_bare_repo(base, gitdir="b.git"):
    bare = base / gitdir
    bare.mkdir(parents=True)
    git(bare, "init", "-q", "--bare", "-b", "main")
    a, b = base / "A", base / "B"
    git(bare, "worktree", "add", "-q", "-b", "wa", str(a))
    git(bare, "worktree", "add", "-q", "-b", "wb", str(b))
    for wt in (a, b):
        git(wt, "config", "user.name", "Test")
        git(wt, "config", "user.email", "test@example.invalid")
        git(wt, "commit", "-q", "--allow-empty", "-m", "first")
    return a, b


def load(capsys):
    capsys.readouterr()
    assert main(["load"]) == 0
    return capsys.readouterr().out


def test_worktrees_of_a_bare_repo_share_one_memory(tmp_path, monkeypatch, capsys):
    a, b = worktrees_of_a_bare_repo(tmp_path)
    monkeypatch.chdir(a)
    assert main(["init", "--no-default-rules"]) == 0
    assert main(["add", "fact from A"]) == 0
    memdir = tmp_path / "b.memory"
    assert (memdir / "facts").is_dir()
    assert (a / "memory-bank").resolve() == memdir.resolve()
    assert (b / "memory-bank").resolve() == memdir.resolve()
    monkeypatch.chdir(b)
    assert "fact from A" in load(capsys)
    assert main(["add", "fact from B"]) == 0
    assert main(["check", "--strict"]) == 0
    monkeypatch.chdir(a)
    assert "fact from B" in load(capsys)


def test_no_folder_or_link_is_written_into_the_bare_repo(tmp_path, monkeypatch):
    a, _ = worktrees_of_a_bare_repo(tmp_path)
    monkeypatch.chdir(a)
    assert main(["init", "--no-default-rules"]) == 0
    assert not (tmp_path / "b.git" / "memory-bank").exists()
    project = find_project(a)
    assert tmp_path / "b.git" not in project.checkouts


def test_path_flag_is_shared_by_every_worktree(tmp_path, monkeypatch, capsys):
    a, b = worktrees_of_a_bare_repo(tmp_path)
    monkeypatch.chdir(a)
    assert main(["init", "--no-default-rules", "--path", str(tmp_path / "mine")]) == 0
    assert main(["add", "fact in mine"]) == 0
    monkeypatch.chdir(b)
    assert resolve_memory_dir(find_project(b))[0] == tmp_path / "mine"
    assert "fact in mine" in load(capsys)


@pytest.mark.parametrize(
    ("gitdir", "expected"),
    [("b.git", "b.memory"), ("proj.git", "proj.memory")],
)
def test_default_name_drops_the_git_suffix(tmp_path, gitdir, expected):
    a, _ = worktrees_of_a_bare_repo(tmp_path, gitdir)
    assert resolve_memory_dir(find_project(a))[0] == tmp_path / expected


def test_hidden_bare_folder_names_the_memory_after_its_parent(tmp_path):
    proj = tmp_path / "proj"
    a, _ = worktrees_of_a_bare_repo(proj, ".bare")
    (proj / ".git").write_text("gitdir: ./.bare\n")
    assert resolve_memory_dir(find_project(a))[0] == proj / "proj.memory"


def test_worktrees_of_a_submodule_share_one_memory(repo, tmp_path, monkeypatch, capsys):
    source = tmp_path / "libsrc"
    source.mkdir()
    git(source, "init", "-q", "-b", "main")
    git(source, "config", "user.name", "Test")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "commit", "-q", "--allow-empty", "-m", "first")
    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "lib")
    lib = repo / "lib"
    other = tmp_path / "lib-wt"
    git(lib, "worktree", "add", "-q", "-b", "other", str(other))
    assert resolve_memory_dir(find_project(lib))[0] == resolve_memory_dir(find_project(other))[0]
    assert find_project(other).main_root == lib
