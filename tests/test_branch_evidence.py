"""A branch in no ref ends a note only when a record says that the branch existed."""

from __future__ import annotations

import pytest
from conftest import add_worktree, git

from cairnkit import autotidy
from cairnkit.cli import main
from cairnkit.memory import Memory
from cairnkit.paths import find_project, merged_checker

ADD = ["--area", "x", "--basis", "seen", "--source", "session:1"]


def _memory():
    return Memory.open(find_project(), None)


def _commit(path, name):
    (path / name).write_text(f"{name}\n")
    git(path, "add", name)
    git(path, "commit", "-qm", f"add {name}")


def _add(capsys, *args):
    capsys.readouterr()
    assert main(["add", "Note on a branch.", *ADD, *args]) == 0
    out = capsys.readouterr().out
    return out.split("added ")[1].split()[0], out


def _retired():
    return [item.id for item in autotidy.find(_memory())]


def _merge_and_delete(repo, branch, how="--no-ff"):
    git(repo, "switch", "-q", "main")
    if how == "--squash":
        git(repo, "merge", "-q", "--squash", branch)
        git(repo, "commit", "-qm", f"{branch} (#1)")
    else:
        git(repo, "merge", "-q", how, "--no-edit", branch)
    git(repo, "branch", "-qD", branch)


@pytest.fixture
def remote(repo, tmp_path):
    bare = tmp_path / "bare.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    return bare


def test_add_records_the_tip_of_the_branch(mem, repo, capsys):
    git(repo, "switch", "-qc", "work")
    fact, _ = _add(capsys, "--short")
    assert _memory().fact(fact)["branch_tip"] == git(repo, "rev-parse", "work").strip()


def test_add_records_the_tip_of_a_remote_copy(mem, repo, capsys, remote):
    git(repo, "update-ref", "refs/remotes/origin/far", "HEAD")
    fact, _ = _add(capsys, "--until-merged", "far")
    assert _memory().fact(fact)["branch_tip"] == git(repo, "rev-parse", "HEAD").strip()


def test_a_typo_stays_open_and_the_add_output_says_so_at_once(mem, repo, capsys):
    fact, out = _add(capsys, "--short", "--until-merged", "feat/typo")
    state = _memory().fact(fact)
    assert "branch_tip" not in state
    assert "no branch feat/typo" in out and "Check the name" in out
    assert f"memory change {fact}" in out
    assert _retired() == []
    assert merged_checker(repo)("feat/typo", None) is False


def test_tidy_says_unknown_for_a_branch_that_it_cannot_read(mem, repo, capsys):
    fact, _ = _add(capsys, "--until-merged", "feat/typo")
    capsys.readouterr()
    assert main(["tidy", "--auto", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Nothing to retire." in out
    assert "unknown" in out and fact in out and "feat/typo" in out
    assert main(["tidy"]) == 0
    assert fact in capsys.readouterr().out


def test_a_fact_with_no_record_stays_when_its_branch_is_gone(repo):
    assert merged_checker(repo)("gone", None) is False


@pytest.mark.parametrize("how", ["--ff", "--no-ff", "--squash"])
def test_merged_and_deleted_ends_the_note(mem, repo, capsys, how):
    git(repo, "switch", "-qc", "work")
    fact, _ = _add(capsys, "--short")
    _commit(repo, "a")
    assert _retired() == []
    _merge_and_delete(repo, "work", how)
    assert _retired() == [fact]
    assert "merged or deleted" in autotidy.find(_memory())[0].reason


def test_squash_merged_and_deleted_on_both_sides_ends_the_note(mem, repo, capsys, remote):
    git(repo, "switch", "-qc", "work")
    fact, _ = _add(capsys, "--short")
    _commit(repo, "a")
    git(repo, "push", "-q", "-u", "origin", "work")
    _merge_and_delete(repo, "work", "--squash")
    assert _retired() == []
    git(repo, "push", "-q", "origin", "main", ":work")
    git(repo, "fetch", "-q", "--prune")
    assert _retired() == [fact]


def test_an_open_remote_branch_with_no_local_copy_stays(mem, repo, capsys, remote, tmp_path):
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    git(other, "switch", "-qc", "far")
    git(other, "config", "user.email", "t@example.invalid")
    git(other, "config", "user.name", "t")
    _commit(other, "far")
    git(other, "push", "-q", "origin", "far")
    git(repo, "fetch", "-q")
    fact, out = _add(capsys, "--until-merged", "far")
    assert "no branch" not in out
    assert _memory().fact(fact)["branch_tip"] == git(other, "rev-parse", "far").strip()
    assert _retired() == []


def test_a_worktree_holds_the_note_until_it_is_removed_and_the_branch_is_gone(
    mem, repo, capsys, monkeypatch
):
    path = add_worktree(repo, "work")
    monkeypatch.chdir(path)
    fact, _ = _add(capsys, "--short")
    _commit(path, "a")
    monkeypatch.chdir(repo)
    git(repo, "merge", "-q", "--no-ff", "--no-edit", "work")
    assert _retired() == []
    git(repo, "worktree", "remove", str(path))
    git(repo, "branch", "-qD", "work")
    assert _retired() == [fact]


def test_a_renamed_branch_stays_open_and_ends_when_its_new_name_is_gone(mem, repo, capsys):
    git(repo, "switch", "-qc", "old")
    fact, _ = _add(capsys, "--short")
    _commit(repo, "a")
    git(repo, "branch", "-m", "old", "new")
    git(repo, "switch", "-q", "main")
    assert _retired() == []
    _merge_and_delete(repo, "new")
    assert _retired() == [fact]


def test_a_memory_in_another_clone_does_not_end_a_branch_that_clone_never_saw(
    mem, repo, capsys, remote, tmp_path, monkeypatch
):
    git(repo, "switch", "-qc", "local-only")
    _commit(repo, "a")
    _add(capsys, "--short")
    fresh = tmp_path / "fresh"
    git(tmp_path, "clone", "-q", str(remote), str(fresh))
    monkeypatch.chdir(fresh)
    monkeypatch.setenv("MEMORY_DIR", str(mem))
    assert _retired() == []


def test_a_fresh_clone_ends_a_branch_whose_recorded_tip_is_in_the_base(
    mem, repo, capsys, remote, tmp_path, monkeypatch
):
    git(repo, "switch", "-qc", "work")
    _commit(repo, "a")
    fact, _ = _add(capsys, "--short")
    _merge_and_delete(repo, "work")
    git(repo, "push", "-q", "origin", "main")
    fresh = tmp_path / "fresh"
    git(tmp_path, "clone", "-q", str(remote), str(fresh))
    monkeypatch.chdir(fresh)
    monkeypatch.setenv("MEMORY_DIR", str(mem))
    assert _retired() == [fact]


def test_tidy_records_a_branch_it_sees_and_then_the_note_can_end(mem, repo, capsys):
    fact, _ = _add(capsys, "--until-merged", "later")
    git(repo, "switch", "-qc", "later")
    _commit(repo, "a")
    assert main(["tidy", "--auto"]) == 0
    state = _memory().fact(fact)
    assert state["branch_tip"] == git(repo, "rev-parse", "later").strip()
    assert state["status"] == "active"
    _merge_and_delete(repo, "later")
    assert _retired() == [fact]


def test_the_session_report_mode_also_records_a_branch(mem, repo, capsys):
    fact, _ = _add(capsys, "--until-merged", "later")
    git(repo, "branch", "later")
    autotidy.report(_memory())
    assert "branch_tip" in _memory().fact(fact)


def test_show_names_the_record_in_the_history(mem, repo, capsys):
    fact, _ = _add(capsys, "--until-merged", "later")
    git(repo, "branch", "later")
    assert main(["tidy", "--auto"]) == 0
    capsys.readouterr()
    assert main(["show", fact]) == 0
    tip = git(repo, "rev-parse", "later").strip()
    assert f"branch tip {tip}" in capsys.readouterr().out


def test_a_dry_run_writes_no_record(mem, repo, capsys):
    fact, _ = _add(capsys, "--until-merged", "later")
    git(repo, "branch", "later")
    assert main(["tidy", "--auto", "--dry-run"]) == 0
    assert "branch_tip" not in _memory().fact(fact)


def test_a_record_is_written_once(mem, repo, capsys):
    fact, _ = _add(capsys, "--until-merged", "later")
    git(repo, "branch", "later")
    assert main(["tidy", "--auto"]) == 0
    assert main(["tidy", "--auto"]) == 0
    assert len(_memory().fact(fact)["history"]) == 1


def test_a_rule_until_merged_stops_loading_when_its_branch_ends(mem, repo, capsys):
    git(repo, "switch", "-qc", "work")
    fact, _ = _add(capsys, "--kind", "rule", "--until-merged", "work")
    _commit(repo, "a")
    capsys.readouterr()
    assert main(["load", "--budget", "0"]) == 0
    assert fact in capsys.readouterr().out
    _merge_and_delete(repo, "work", "--squash")
    assert main(["load", "--budget", "0"]) == 0
    assert fact not in capsys.readouterr().out


def test_a_rule_on_a_gone_branch_with_no_record_keeps_loading(mem, repo, capsys):
    fact, _ = _add(capsys, "--kind", "rule", "--until-merged", "feat/typo")
    assert main(["load", "--budget", "0"]) == 0
    assert fact in capsys.readouterr().out


def test_the_record_passes_the_check(mem, repo, capsys):
    git(repo, "switch", "-qc", "work")
    _add(capsys, "--short")
    assert main(["check", "--strict"]) == 0


def test_a_bad_tip_is_refused_by_the_schema():
    from cairnkit.schema import validate_record

    change = {"type": "change", "id": "f-1", "at": "2026-11-01T00:00:00+00:00", "writer": "w"}
    assert validate_record({**change, "branch_tip": "a" * 40}) == []
    assert validate_record({**change, "branch_tip": "not a commit"}) != []
