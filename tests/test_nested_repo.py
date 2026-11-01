"""The memory of a nested repo stays out of every enclosing work tree."""

from conftest import git

from cairnkit.cli import main


def new_repo(path):
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "commit", "-q", "--allow-empty", "-m", "first")
    return path


def submodule(tmp_path):
    source = new_repo(tmp_path / "libsrc")
    parent = new_repo(tmp_path / "parent")
    git(parent, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "lib")
    git(parent, "commit", "-qm", "add lib")
    return parent, parent / "lib"


def assert_parent_never_sees_it(parent, memdir):
    assert (memdir / "facts").is_dir()
    assert git(parent, "status", "--porcelain") == ""
    git(parent, "add", "-A")
    assert git(parent, "diff", "--cached", "--name-only") == ""


def test_submodule_memory_is_outside_the_parent(tmp_path, monkeypatch, capsys):
    parent, lib = submodule(tmp_path)
    monkeypatch.chdir(lib)
    assert main(["init", "--no-default-rules"]) == 0
    assert main(["add", "fact of the submodule"]) == 0
    memdir = tmp_path / "parent.lib.memory"
    assert (lib / "memory-bank").resolve() == memdir.resolve()
    assert not (parent / "lib.memory").exists()
    assert_parent_never_sees_it(parent, memdir)
    capsys.readouterr()
    assert main(["load"]) == 0
    assert "fact of the submodule" in capsys.readouterr().out
    assert main(["check", "--strict"]) == 0


def test_plain_nested_repo_memory_is_outside_the_parent(tmp_path, monkeypatch):
    top = new_repo(tmp_path / "top")
    (top / ".gitignore").write_text("inner/\n")
    git(top, "add", ".gitignore")
    git(top, "commit", "-qm", "ignore inner")
    inner = new_repo(top / "inner")
    monkeypatch.chdir(inner)
    assert main(["init", "--no-default-rules"]) == 0
    assert_parent_never_sees_it(top, tmp_path / "top.inner.memory")


def test_deep_nesting_names_the_whole_path(tmp_path, monkeypatch):
    top = new_repo(tmp_path / "top")
    (top / "a").mkdir()
    (top / ".gitignore").write_text("a/\n")
    git(top, "add", ".gitignore")
    git(top, "commit", "-qm", "ignore a")
    mid = new_repo(top / "a" / "mid")
    (mid / ".gitignore").write_text("deep/\n")
    git(mid, "add", ".gitignore")
    git(mid, "commit", "-qm", "ignore deep")
    deep = new_repo(mid / "deep")
    monkeypatch.chdir(deep)
    assert main(["init", "--no-default-rules"]) == 0
    memdir = tmp_path / "top.a.mid.deep.memory"
    assert (memdir / "facts").is_dir()
    assert git(top, "status", "--porcelain") == ""
    assert git(mid, "status", "--porcelain") == ""


def test_with_no_writable_folder_outside_it_is_excluded_with_proof(tmp_path, monkeypatch):
    real_access = __import__("os").access
    top = new_repo(tmp_path / "top")
    (top / ".gitignore").write_text("inner/\n")
    git(top, "add", ".gitignore")
    git(top, "commit", "-qm", "ignore inner")
    inner = new_repo(top / "inner")
    monkeypatch.chdir(inner)
    monkeypatch.setattr(
        "cairnkit.paths.os.access",
        lambda path, mode: False if path == tmp_path else real_access(path, mode),
    )
    assert main(["init", "--no-default-rules"]) == 0
    memdir = top / "inner.memory"
    assert_parent_never_sees_it(top, memdir)
    git(top, "check-ignore", "-q", "inner.memory")
    assert "/inner.memory" in (top / ".git" / "info" / "exclude").read_text()


def older_memory_inside_parent(tmp_path):
    top = new_repo(tmp_path / "top")
    (top / ".gitignore").write_text("inner/\n")
    git(top, "add", ".gitignore")
    git(top, "commit", "-qm", "ignore inner")
    inner = new_repo(top / "inner")
    memdir = top / "inner.memory"
    for sub in ("facts", "notes", "branches"):
        (memdir / sub).mkdir(parents=True)
    (memdir / "README.md").write_text("old\n")
    return top, inner, memdir


def test_older_memory_in_the_parent_tree_is_excluded_at_the_next_load(
    tmp_path, monkeypatch, capsys
):
    top, inner, memdir = older_memory_inside_parent(tmp_path)
    (inner / "memory-bank").symlink_to("../inner.memory", target_is_directory=True)
    assert "inner.memory" in git(top, "status", "--porcelain")
    monkeypatch.chdir(inner)
    assert main(["load"]) == 0
    assert "# Project memory" in capsys.readouterr().out
    assert_parent_never_sees_it(top, memdir)


def test_older_memory_with_no_link_stays_where_it_is(tmp_path, monkeypatch, capsys):
    top, inner, memdir = older_memory_inside_parent(tmp_path)
    monkeypatch.chdir(inner)
    assert main(["check"]) == 0
    assert (inner / "memory-bank").resolve() == memdir.resolve()
    assert not (tmp_path / "top.inner.memory").exists()
    assert_parent_never_sees_it(top, memdir)


def test_memory_files_the_parent_already_tracks_are_an_error(tmp_path, monkeypatch, capsys):
    top, inner, _memdir = older_memory_inside_parent(tmp_path)
    (inner / "memory-bank").symlink_to("../inner.memory", target_is_directory=True)
    git(top, "add", "-f", "inner.memory/README.md")
    git(top, "commit", "-qm", "the old leak")
    monkeypatch.chdir(inner)
    capsys.readouterr()
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert str(top) in out and "tracks" in out and "rm -r --cached" in out
    assert main(["load"]) == 0


def test_init_path_inside_a_work_tree_is_excluded(repo, capsys):
    assert main(["init", "--no-default-rules", "--path", "private/mem"]) == 0
    assert git(repo, "status", "--porcelain") == ""
    git(repo, "check-ignore", "-q", "private/mem")


def test_init_path_into_tracked_files_is_refused(repo, capsys):
    (repo / "kept").mkdir()
    (repo / "kept" / "a.txt").write_text("a\n")
    git(repo, "add", "kept")
    git(repo, "commit", "-qm", "kept")
    capsys.readouterr()
    assert main(["init", "--no-default-rules", "--path", "kept"]) == 1
    captured = capsys.readouterr()
    assert "tracks" in captured.err and "Nothing changed" in captured.err
    assert not (repo / "kept" / "facts").exists()


def test_hook_env_does_not_confuse_the_walk(tmp_path, monkeypatch):
    top = new_repo(tmp_path / "top")
    (top / ".gitignore").write_text("inner/\n")
    git(top, "add", ".gitignore")
    git(top, "commit", "-qm", "ignore inner")
    inner = new_repo(top / "inner")
    monkeypatch.chdir(inner)
    monkeypatch.setenv("GIT_DIR", str(inner / ".git"))
    assert main(["init", "--no-default-rules"]) == 0
    assert (tmp_path / "top.inner.memory" / "facts").is_dir()
