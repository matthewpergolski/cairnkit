"""A memory has one owner. Setup never refuses for a neighbor, and a backup never wins."""

import os
import shutil

from conftest import git

from cairnkit.cli import main

FACT = "Trap: billing webhook retries forever"
OTHER = "belongs to another project"


def run(capsys, *args):
    capsys.readouterr()
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def new_repo(parent, name, commit=True):
    folder = parent / name
    folder.mkdir(parents=True)
    git(folder, "init", "-q", "-b", "main")
    git(folder, "config", "user.name", "Test")
    git(folder, "config", "user.email", "t@example.invalid")
    if commit:
        (folder / "a.txt").write_text(name)
        git(folder, "add", "a.txt")
        git(folder, "commit", "-q", "-m", f"first of {name}")
    return folder


def with_fact(capsys, text=FACT):
    add = ["add", text, "--kind", "trap", "--pinned", "--basis", "seen", "--source", "s:1"]
    assert main(add) == 0
    assert main(["load"]) == 0
    capsys.readouterr()


def init(*extra):
    return main(["init", "--no-default-rules", *extra])


def neighbor_with_custom_memory(parent, monkeypatch, capsys):
    other = new_repo(parent, "other")
    monkeypatch.chdir(other)
    assert init("--path", "../foreign6") == 0
    with_fact(capsys)
    return parent / "foreign6"


# --- init beside a neighbor -----------------------------------------------------


def test_empty_repo_beside_a_live_custom_memory_gets_its_own(tmp_path, monkeypatch, capsys):
    foreign = neighbor_with_custom_memory(tmp_path, monkeypatch, capsys)
    new = new_repo(tmp_path, "new", commit=False)
    monkeypatch.chdir(new)
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert str(foreign) not in out
    assert (new / "memory-bank").resolve() == (tmp_path / "new.memory").resolve()
    code, out = run(capsys, "hook", "session-start", "--agent", "generic")
    assert code == 0 and "not loaded" not in out and FACT not in out


def test_plain_folder_beside_a_live_custom_memory_gets_its_own(tmp_path, monkeypatch, capsys):
    foreign = neighbor_with_custom_memory(tmp_path, monkeypatch, capsys)
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert str(foreign) not in out


def test_a_custom_named_folder_with_no_id_is_never_offered(repo, capsys, tmp_path):
    other = tmp_path / "some-notes"
    (other / "facts").mkdir(parents=True)
    (other / "config.toml").write_text("")
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert "some-notes" not in out


def test_a_memory_with_a_gone_project_name_is_named_once(repo, capsys, tmp_path):
    gone = tmp_path / "gone.memory"
    (gone / "facts").mkdir(parents=True)
    (gone / "config.toml").write_text("")
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert out.count(str(gone)) == 1 and f"memory init --path {gone}" in out
    assert (repo / "memory-bank").resolve() == (tmp_path / "proj.memory").resolve()
    code, out = run(capsys, "load")
    assert str(gone) not in out


def test_an_empty_repo_is_not_offered_a_memory_that_had_commits(tmp_path, monkeypatch, capsys):
    old = new_repo(tmp_path, "old")
    monkeypatch.chdir(old)
    assert init() == 0
    with_fact(capsys)
    (old / "memory-bank").unlink()
    (old / ".git" / "cairnkit-memory").unlink()
    shutil.rmtree(old)
    new = new_repo(tmp_path, "new", commit=False)
    monkeypatch.chdir(new)
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert "old.memory" not in out


def test_session_start_gives_a_connected_project_its_memory(tmp_path, monkeypatch, capsys):
    neighbor_with_custom_memory(tmp_path, monkeypatch, capsys)
    gone = tmp_path / "gone.memory"
    (gone / "facts").mkdir(parents=True)
    (gone / "config.toml").write_text("")
    new = new_repo(tmp_path, "new", commit=False)
    monkeypatch.chdir(new)
    (new / ".claude").mkdir()
    assert main(["hooks", "install", "--agent", "claude"]) == 0
    code, out = run(capsys, "hook", "session-start", "--agent", "claude")
    assert code == 0 and "not loaded" not in out
    assert (tmp_path / "new.memory" / "facts").is_dir()
    assert (new / "memory-bank").is_symlink()
    assert f"memory init --path {gone}" in out


def test_session_start_without_a_connection_makes_no_memory(tmp_path, monkeypatch, capsys):
    new = new_repo(tmp_path, "new", commit=False)
    monkeypatch.chdir(new)
    code, _ = run(capsys, "hook", "session-start", "--agent", "generic")
    assert code == 0
    assert not (tmp_path / "new.memory").exists()


# --- a copied repo --------------------------------------------------------------


def copied(repo, capsys, tmp_path, monkeypatch):
    with_fact(capsys)
    copy = tmp_path / "copy"
    shutil.copytree(repo, copy, symlinks=True)
    monkeypatch.chdir(copy)
    return copy


def test_a_copy_hears_it_once(repo, mem, capsys, tmp_path, monkeypatch):
    copied(repo, capsys, tmp_path, monkeypatch)
    _, first = run(capsys, "load")
    _, second = run(capsys, "load")
    assert OTHER in first and str(repo) in first
    assert OTHER not in second


def test_an_add_in_a_copy_hears_it_when_no_load_came_first(
    repo, mem, capsys, tmp_path, monkeypatch
):
    copied(repo, capsys, tmp_path, monkeypatch)
    _, out = run(capsys, "add", "from the copy", "--basis", "seen", "--source", "s:1")
    assert OTHER in out


def test_check_in_a_copy_always_says_it(repo, mem, capsys, tmp_path, monkeypatch):
    copied(repo, capsys, tmp_path, monkeypatch)
    run(capsys, "load")
    for _ in range(2):
        code, out = run(capsys, "check", "--strict")
        assert code == 0 and OTHER in out


def test_the_next_init_gives_a_copy_its_own_memory(repo, mem, capsys, tmp_path, monkeypatch):
    copy = copied(repo, capsys, tmp_path, monkeypatch)
    before = (mem / "facts").iterdir().__next__().read_bytes()
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert str(mem) in out
    own = tmp_path / "copy.memory"
    assert (copy / "memory-bank").resolve() == own.resolve()
    assert main(["add", "copy only", "--basis", "seen", "--source", "s:1"]) == 0
    assert (mem / "facts").iterdir().__next__().read_bytes() == before
    code, out = run(capsys, "load")
    assert OTHER not in out and FACT not in out
    monkeypatch.chdir(repo)
    code, out = run(capsys, "load")
    assert OTHER not in out and FACT in out
    assert (repo / "memory-bank").resolve() == mem.resolve()


def test_init_in_a_copy_drops_the_copied_path_file(tmp_path, repo, capsys, monkeypatch):
    assert init("--path", "../custom") == 0
    with_fact(capsys)
    copy = tmp_path / "copy"
    shutil.copytree(repo, copy, symlinks=True)
    monkeypatch.chdir(copy)
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert (copy / "memory-bank").resolve() == (tmp_path / "copy.memory").resolve()
    assert not (copy / ".memory-path").exists()
    assert (repo / ".memory-path").is_file()


def test_a_copy_whose_source_is_gone_is_a_move(repo, mem, capsys, tmp_path, monkeypatch):
    copy = copied(repo, capsys, tmp_path, monkeypatch)
    shutil.rmtree(repo)
    code, out = run(capsys, "load")
    assert code == 0 and FACT in out and OTHER not in out
    run(capsys, "init", "--no-default-rules")
    assert (copy / "memory-bank").resolve() == mem.resolve()


def test_a_rename_is_not_a_copy(repo, mem, capsys, tmp_path, monkeypatch):
    with_fact(capsys)
    new = tmp_path / "renamed"
    repo.rename(new)
    monkeypatch.chdir(new)
    code, out = run(capsys, "load")
    assert FACT in out and OTHER not in out
    code, out = run(capsys, "check", "--strict")
    assert code == 0 and OTHER not in out


def test_a_linked_worktree_is_the_same_project(repo, mem, capsys, monkeypatch):
    from conftest import add_worktree

    with_fact(capsys)
    worktree = add_worktree(repo, "topic")
    monkeypatch.chdir(worktree)
    _code, out = run(capsys, "load")
    assert FACT in out and OTHER not in out


# --- two projects on purpose or by mistake ----------------------------------------


def shared_by_two(tmp_path, monkeypatch, capsys):
    a = new_repo(tmp_path, "a")
    monkeypatch.chdir(a)
    assert init("--path", "../shared") == 0
    with_fact(capsys)
    b = new_repo(tmp_path, "b")
    monkeypatch.chdir(b)
    return a, b


def test_path_to_another_projects_memory_is_honored_and_said(tmp_path, monkeypatch, capsys):
    a, b = shared_by_two(tmp_path, monkeypatch, capsys)
    code, out = run(capsys, "init", "--no-default-rules", "--path", "../shared")
    assert code == 0, out
    assert OTHER in out and str(a) in out
    assert (b / "memory-bank").resolve() == (tmp_path / "shared").resolve()
    for _ in range(2):
        _, out = run(capsys, "load")
        assert FACT in out and out.count(OTHER) == 1
    code, out = run(capsys, "check", "--strict")
    assert code == 0 and OTHER in out


def test_init_again_keeps_a_stated_path(tmp_path, monkeypatch, capsys):
    _, b = shared_by_two(tmp_path, monkeypatch, capsys)
    assert init("--path", "../shared") == 0
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0 and OTHER in out
    assert (b / "memory-bank").resolve() == (tmp_path / "shared").resolve()


def test_the_owner_hears_nothing(tmp_path, monkeypatch, capsys):
    a, _ = shared_by_two(tmp_path, monkeypatch, capsys)
    assert init("--path", "../shared") == 0
    monkeypatch.chdir(a)
    _, out = run(capsys, "load")
    assert OTHER not in out


def test_stated_sharing_silences_the_line(tmp_path, monkeypatch, capsys):
    _, b = shared_by_two(tmp_path, monkeypatch, capsys)
    assert init("--path", "../shared") == 0
    git(b, "config", "cairnkit.sharedmemory", "true")
    _, out = run(capsys, "load")
    assert FACT in out and OTHER not in out
    code, out = run(capsys, "init", "--no-default-rules", "--path", "../shared")
    assert code == 0 and OTHER not in out


def test_a_fork_with_path_hears_the_same_line(repo, mem, capsys, tmp_path, monkeypatch):
    with_fact(capsys)
    fork = tmp_path / "fork"
    git(tmp_path, "clone", "-q", str(repo), str(fork))
    monkeypatch.chdir(fork)
    code, out = run(capsys, "init", "--no-default-rules", "--path", str(mem))
    assert code == 0 and OTHER in out
    _, out = run(capsys, "load")
    assert OTHER in out


def test_a_memory_from_before_the_owner_line_with_other_roots_is_named(
    tmp_path, monkeypatch, capsys
):
    a, _ = shared_by_two(tmp_path, monkeypatch, capsys)
    shared = tmp_path / "shared"
    lines = (shared / ".identity").read_text().splitlines()
    (shared / ".identity").write_text("\n".join(lines[:2]) + "\n")
    shutil.rmtree(a)
    assert init("--path", "../shared") == 0
    _, out = run(capsys, "load")
    assert OTHER in out


def test_a_memory_from_before_the_owner_line_gets_one(repo, mem, capsys):
    with_fact(capsys)
    lines = (mem / ".identity").read_text().splitlines()
    (mem / ".identity").write_text("\n".join(lines[:2]) + "\n")
    _, out = run(capsys, "load")
    assert OTHER not in out
    assert str((repo / ".git").resolve()) in (mem / ".identity").read_text()


def test_a_rewritten_history_stays_the_owner(repo, mem, capsys):
    with_fact(capsys)
    lines = (mem / ".identity").read_text().splitlines()
    lines[1] = "0" * 40
    (mem / ".identity").write_text("\n".join(lines) + "\n")
    _, out = run(capsys, "load")
    assert OTHER not in out


def test_a_load_from_env_does_not_change_the_owner(repo, mem, capsys, tmp_path, monkeypatch):
    with_fact(capsys)
    before = (mem / ".identity").read_text()
    other = new_repo(tmp_path, "other")
    monkeypatch.chdir(other)
    monkeypatch.setenv("MEMORY_DIR", str(mem))
    _, out = run(capsys, "load")
    assert FACT in out and OTHER in out
    assert (mem / ".identity").read_text() == before


# --- self-repair ----------------------------------------------------------------


def test_two_backups_adopt_none_and_name_both(repo, mem, capsys, tmp_path):
    with_fact(capsys, "old fact")
    old = tmp_path / "proj.memory-bak-old"
    shutil.copytree(mem, old)
    with_fact(capsys, "NEW important fact")
    new = tmp_path / "zz-new-backup"
    shutil.copytree(mem, new)
    shutil.rmtree(mem)
    code, out = run(capsys, "load")
    assert code == 0 and str(old) in out and str(new) in out
    assert "memory init --path" in out and "old fact" not in out
    assert os.readlink(repo / "memory-bank") == "../proj.memory"
    code, out = run(capsys, "check")
    assert code == 1 and str(old) in out and str(new) in out
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 1 and str(new) in out and "Nothing changed" in out
    assert not mem.exists()


def test_a_chosen_backup_comes_back_with_all_its_facts(repo, mem, capsys, tmp_path):
    with_fact(capsys)
    backup = tmp_path / "zz-new-backup"
    shutil.copytree(mem, backup)
    shutil.copytree(mem, tmp_path / "older-copy")
    shutil.rmtree(mem)
    code, out = run(capsys, "init", "--no-default-rules", "--path", str(backup))
    assert code == 0, out
    _, out = run(capsys, "load")
    assert FACT in out and OTHER not in out


def test_one_copy_with_another_name_is_named_and_not_adopted(repo, mem, capsys, tmp_path):
    with_fact(capsys)
    backup = tmp_path / "proj.memory-bak"
    mem.rename(backup)
    code, out = run(capsys, "load")
    assert code == 0 and FACT not in out
    assert f"memory init --path {backup}" in out
    assert os.readlink(repo / "memory-bank") == "../proj.memory"


def test_a_copy_with_the_recorded_name_returns(repo, mem, capsys, tmp_path, monkeypatch):
    with_fact(capsys)
    far = tmp_path / "far"
    far.mkdir()
    mem.rename(far / "proj.memory")
    repo.rename(far / "proj")
    monkeypatch.chdir(far / "proj")
    _, out = run(capsys, "load")
    assert FACT in out
    assert (far / "proj" / "memory-bank").resolve() == (far / "proj.memory").resolve()


def test_a_memory_named_for_the_project_returns(repo, mem, capsys, tmp_path, monkeypatch):
    with_fact(capsys)
    new = tmp_path / "renamed"
    repo.rename(new)
    mem.rename(tmp_path / "renamed.memory")
    monkeypatch.chdir(new)
    _, out = run(capsys, "load")
    assert FACT in out
    assert (new / "memory-bank").resolve() == (tmp_path / "renamed.memory").resolve()


def test_a_backup_does_not_beat_the_project_name(repo, mem, capsys, tmp_path, monkeypatch):
    with_fact(capsys)
    new = tmp_path / "renamed"
    repo.rename(new)
    good = tmp_path / "renamed.memory"
    mem.rename(good)
    shutil.copytree(good, tmp_path / "proj.memory-x")
    monkeypatch.chdir(new)
    _, out = run(capsys, "load")
    assert FACT in out
    assert (new / "memory-bank").resolve() == good.resolve()


def test_a_copied_plain_folder_hears_no_git_advice_and_gets_its_own(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "pl"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert init() == 0
    with_fact(capsys)
    copy = tmp_path / "pl2"
    shutil.copytree(plain, copy, symlinks=True)
    monkeypatch.chdir(copy)
    _, out = run(capsys, "load")
    assert OTHER in out and "git config" not in out
    assert init() == 0
    assert (copy / "memory-bank").resolve() == (tmp_path / "pl2.memory").resolve()
