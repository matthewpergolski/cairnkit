"""A renamed or moved project, or a moved memory folder, keeps its facts."""

import json
import os
import subprocess

from conftest import git

from cairnkit.cli import main

FACT = "Trap: billing webhook retries forever"


def run(capsys, *args):
    capsys.readouterr()
    code = main(list(args))
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def stored(repo, mem, capsys):
    assert main(["add", FACT, "--kind", "trap", "--pinned"]) == 0
    assert main(["load"]) == 0
    capsys.readouterr()
    return mem


def move(repo, new, monkeypatch):
    new.parent.mkdir(parents=True, exist_ok=True)
    repo.rename(new)
    monkeypatch.chdir(new)
    return new


def memories_beside(folder):
    return sorted(p.name for p in folder.parent.iterdir() if (p / "facts").is_dir())


# --- the link still resolves ---------------------------------------------------


def test_renamed_repo_just_works_through_its_link(repo, mem, capsys, monkeypatch):
    stored(repo, mem, capsys)
    new = move(repo, repo.parent / "renamed", monkeypatch)
    code, out = run(capsys, "load")
    assert code == 0 and FACT in out
    assert str(mem) in out
    code, out = run(capsys, "check", "--strict")
    assert code == 0, out
    assert (new / "memory-bank").resolve() == mem.resolve()
    assert not (repo.parent / "renamed.memory").exists()


def test_init_after_a_rename_keeps_the_valid_link(repo, mem, capsys, monkeypatch):
    stored(repo, mem, capsys)
    new = move(repo, repo.parent / "renamed", monkeypatch)
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert (new / "memory-bank").resolve() == mem.resolve()
    assert not (repo.parent / "renamed.memory").exists()
    assert FACT in run(capsys, "load")[1]


def test_valid_link_wins_over_an_unrelated_folder_with_the_new_name(repo, mem, capsys, monkeypatch):
    stored(repo, mem, capsys)
    other = repo.parent / "renamed.memory"
    (other / "facts").mkdir(parents=True)
    move(repo, repo.parent / "renamed", monkeypatch)
    assert FACT in run(capsys, "load")[1]


def test_link_to_a_folder_with_no_memory_does_not_win(repo, mem, capsys, tmp_path):
    other = tmp_path / "not-memory"
    other.mkdir()
    (repo / "memory-bank").unlink()
    (repo / "memory-bank").symlink_to(other)
    assert FACT not in run(capsys, "load")[1]
    assert (repo / "memory-bank").resolve() == other.resolve()
    code, out = run(capsys, "check")
    assert code == 1 and "points to" in out


def test_init_path_to_an_empty_folder_never_replaces_a_valid_link(repo, mem, capsys, tmp_path):
    stored(repo, mem, capsys)
    code, out = run(capsys, "init", "--path", str(tmp_path / "typo"))
    assert code == 1
    assert str(mem) in out and "Nothing changed" in out
    assert (repo / "memory-bank").resolve() == mem.resolve()
    assert not (tmp_path / "typo").exists()
    assert not (repo / ".memory-path").exists()


def test_init_path_to_an_existing_memory_moves_the_link(repo, mem, capsys, tmp_path):
    stored(repo, mem, capsys)
    new = tmp_path / "far" / "away"
    new.parent.mkdir()
    mem.rename(new)
    (repo / "memory-bank").unlink()
    (repo / "memory-bank").symlink_to(mem, target_is_directory=True)
    code, out = run(capsys, "init", "--no-default-rules", "--path", str(new))
    assert code == 0, out
    assert (repo / "memory-bank").resolve() == new.resolve()
    assert FACT in run(capsys, "load")[1]


def test_valid_link_of_a_plain_folder_wins(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "pl"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert main(["init", "--no-default-rules"]) == 0
    assert main(["add", FACT]) == 0
    new = tmp_path / "pl2"
    plain.rename(new)
    monkeypatch.chdir(new)
    assert FACT in run(capsys, "load")[1]
    assert run(capsys, "check", "--strict")[0] == 0


def test_a_worktree_link_finds_the_memory_when_the_main_link_is_gone(
    repo, mem, capsys, monkeypatch
):
    from conftest import add_worktree

    stored(repo, mem, capsys)
    add_worktree(repo, "keep")
    assert main(["check"]) == 0
    (repo / "memory-bank").unlink()
    (repo / ".git" / "cairnkit-memory").unlink()
    new = move(repo, repo.parent / "renamed", monkeypatch)
    wt = new / ".worktrees" / "keep"
    repaired = subprocess.run(["git", "worktree", "repair", str(wt)], cwd=new, capture_output=True)
    assert repaired.returncode == 0
    assert FACT in run(capsys, "load")[1]


# --- the link dangles ----------------------------------------------------------


def test_repo_moved_to_another_parent_relinks_by_itself(repo, mem, capsys, monkeypatch, tmp_path):
    stored(repo, mem, capsys)
    new = move(repo, tmp_path / "other" / "proj", monkeypatch)
    assert not (new / "memory-bank").exists()
    code, out = run(capsys, "load")
    assert code == 0 and FACT in out
    assert "relinked" in out
    assert (new / "memory-bank").resolve() == mem.resolve()
    assert not os.path.isabs(os.readlink(new / "memory-bank"))
    assert run(capsys, "check", "--strict")[0] == 0
    assert not (tmp_path / "other" / "proj.memory").exists()
    assert git(new, "status", "--porcelain") == ""


def test_session_start_after_a_move_brings_the_facts(repo, mem, capsys, monkeypatch, tmp_path):
    stored(repo, mem, capsys)
    move(repo, tmp_path / "other" / "proj", monkeypatch)
    code, out = run(capsys, "hook", "session-start", "--agent", "pi")
    assert code == 0 and FACT in out


def test_memory_renamed_beside_the_repo_is_named_with_one_command(repo, mem, capsys, tmp_path):
    stored(repo, mem, capsys)
    new = tmp_path / "elsewhere"
    mem.rename(new)
    code, out = run(capsys, "load")
    assert code == 0 and FACT not in out
    assert f"memory init --path {new}" in out
    assert run(capsys, "init", "--no-default-rules", "--path", str(new))[0] == 0
    assert FACT in run(capsys, "load")[1]
    assert (repo / "memory-bank").resolve() == new.resolve()
    assert not mem.exists()
    assert run(capsys, "check", "--strict")[0] == 0


def test_memory_renamed_beside_its_old_place_is_named(repo, capsys, tmp_path):
    keep = tmp_path / "keep"
    keep.mkdir()
    place = keep / "one"
    assert main(["init", "--no-default-rules", "--path", str(place)]) == 0
    assert main(["add", FACT]) == 0
    assert main(["load"]) == 0
    place.rename(keep / "two")
    _code, out = run(capsys, "load")
    assert FACT not in out and f"memory init --path {keep / 'two'}" in out


def test_memory_moved_out_of_reach_says_what_is_needed(repo, mem, capsys, tmp_path):
    stored(repo, mem, capsys)
    far = tmp_path / "x" / "y" / "far"
    far.parent.mkdir(parents=True)
    mem.rename(far)
    code, out = run(capsys, "load")
    assert code == 0
    assert str(mem) in out and "memory init --path" in out
    assert "run `memory init`" not in out
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 1 and "Nothing changed" in out and "memory init --path" in out
    assert not mem.exists()
    code, out = run(capsys, "check")
    assert code == 1 and "memory init --path" in out
    code, out = run(capsys, "init", "--no-default-rules", "--path", str(far))
    assert code == 0, out
    assert FACT in run(capsys, "load")[1]


def test_session_start_says_a_memory_is_lost(repo, mem, capsys, tmp_path):
    stored(repo, mem, capsys)
    far = tmp_path / "x" / "far"
    far.parent.mkdir()
    mem.rename(far)
    code, out = run(capsys, "hook", "session-start", "--agent", "pi")
    assert code == 0
    assert "memory init --path" in out


def test_a_new_memory_can_still_be_started_on_purpose(repo, mem, capsys, tmp_path):
    stored(repo, mem, capsys)
    mem.rename(tmp_path / "x")
    (tmp_path / "x" / ".identity").unlink()
    new = tmp_path / "fresh"
    code, out = run(capsys, "init", "--no-default-rules", "--path", str(new))
    assert code == 0, out
    assert (repo / "memory-bank").resolve() == new.resolve()


def test_a_folder_with_another_memory_id_is_not_taken(repo, mem, capsys, tmp_path):
    stored(repo, mem, capsys)
    moved = tmp_path / "moved"
    mem.rename(moved)
    (moved / ".identity").write_text("another-id\n")
    code, out = run(capsys, "load")
    assert code == 0 and FACT not in out
    assert (repo / "memory-bank").is_symlink() and not (repo / "memory-bank").exists()


# --- no link at all ------------------------------------------------------------


def test_sibling_under_the_old_name_with_no_link_returns(repo, mem, capsys, monkeypatch):
    stored(repo, mem, capsys)
    (repo / "memory-bank").unlink()
    new = move(repo, repo.parent / "renamed", monkeypatch)
    _code, out = run(capsys, "load")
    assert FACT in out
    assert (new / "memory-bank").resolve() == mem.resolve()
    assert memories_beside(new) == ["proj.memory"]


def old_install_beside_a_new_clone(repo, mem, capsys, monkeypatch, tmp_path):
    """A memory from before this version: no id, no record in the repo. Its remote names it."""
    stored(repo, mem, capsys)
    (mem / ".identity").unlink()
    (repo / "memory-bank").unlink()
    (repo / ".git" / "cairnkit-memory").unlink()
    new = move(repo, repo.parent / "renamed", monkeypatch)
    git(new, "remote", "add", "origin", "https://example.com/someone/proj.git")
    return new


def test_old_sibling_with_no_proof_is_named_and_not_replaced(
    repo, mem, capsys, monkeypatch, tmp_path
):
    new = old_install_beside_a_new_clone(repo, mem, capsys, monkeypatch, tmp_path)
    code, out = run(capsys, "load")
    assert code == 0
    assert str(mem) in out and f"memory init --path {mem}" in out
    assert FACT not in out
    code, out = run(capsys, "check")
    assert code == 0 and str(mem) in out
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert f"memory init --path {mem}" in out
    assert memories_beside(new) == ["proj.memory", "renamed.memory"]
    assert (new / "memory-bank").resolve() == (new.parent / "renamed.memory").resolve()
    code, out = run(capsys, "init", "--no-default-rules", "--path", str(mem))
    assert code == 0, out
    assert FACT in run(capsys, "load")[1]


def test_memory_of_a_folder_that_still_exists_is_not_named(repo, capsys, tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    (tmp_path / "live.memory" / "facts").mkdir(parents=True)
    (tmp_path / "live.memory" / "config.toml").write_text("")
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert "live.memory" not in out


def test_memory_of_another_repo_is_not_named(repo, capsys, tmp_path):
    other = tmp_path / "gone.memory"
    (other / "facts").mkdir(parents=True)
    (other / "config.toml").write_text("")
    (other / ".identity").write_text("some-id\n0000000000000000000000000000000000000000\n")
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert "gone.memory" not in out


def test_a_clone_beside_a_memory_of_the_same_history_names_it(repo, mem, capsys, monkeypatch):
    stored(repo, mem, capsys)
    clone = repo.parent / "clone"
    git(repo.parent, "clone", "-q", str(repo), str(clone))
    git(clone, "config", "user.name", "Test")
    (repo / "memory-bank").unlink()
    import shutil

    shutil.rmtree(repo)
    monkeypatch.chdir(clone)
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0 and f"memory init --path {mem}" in out
    assert (clone / "memory-bank").resolve() == (repo.parent / "clone.memory").resolve()


def test_two_clones_keep_their_own_memories(repo, mem, capsys, monkeypatch):
    stored(repo, mem, capsys)
    clone = repo.parent / "clone"
    git(repo.parent, "clone", "-q", str(repo), str(clone))
    monkeypatch.chdir(clone)
    code, out = run(capsys, "init", "--no-default-rules")
    assert code == 0, out
    assert (clone / "memory-bank").resolve() == (repo.parent / "clone.memory").resolve()
    assert FACT not in run(capsys, "load")[1]


# --- what the record is --------------------------------------------------------


def test_record_stays_out_of_git_and_out_of_the_load(repo, mem, capsys):
    stored(repo, mem, capsys)
    record = (repo / ".git" / "cairnkit-memory").read_text().splitlines()
    identity = (mem / ".identity").read_text().splitlines()
    assert record == [identity[0], str(mem.resolve()), str((repo / ".git").resolve())]
    assert identity[2] == str((repo / ".git").resolve())
    assert identity[1] == git(repo, "rev-list", "--max-parents=0", "HEAD").strip()
    assert git(repo, "status", "--porcelain") == ""
    assert identity[0] not in run(capsys, "load")[1]


def test_flag_and_env_leave_no_record(repo, mem, capsys, tmp_path, monkeypatch):
    stored(repo, mem, capsys)
    before = (repo / ".git" / "cairnkit-memory").read_text()
    other = tmp_path / "other"
    (other / "facts").mkdir(parents=True)
    monkeypatch.setenv("MEMORY_DIR", str(other))
    assert main(["load"]) == 0
    assert (repo / ".git" / "cairnkit-memory").read_text() == before
    assert not (other / ".identity").exists()


def test_a_read_only_memory_still_loads(repo, mem, capsys):
    stored(repo, mem, capsys)
    (mem / ".identity").unlink()
    mem.chmod(0o555)
    try:
        code, out = run(capsys, "load")
    finally:
        mem.chmod(0o755)
    assert code == 0 and FACT in out


def test_fact_files_are_untouched_by_a_move(repo, mem, capsys, monkeypatch, tmp_path):
    stored(repo, mem, capsys)
    before = (mem / "facts" / "main.jsonl").read_bytes()
    move(repo, tmp_path / "other" / "proj", monkeypatch)
    run(capsys, "load")
    run(capsys, "check")
    assert (mem / "facts" / "main.jsonl").read_bytes() == before
    assert json.loads(before.splitlines()[0])["text"] == FACT
