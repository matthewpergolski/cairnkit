"""During a rebase HEAD is detached. A note belongs to the branch being rebased."""

import subprocess

from conftest import git

from cairnkit.cli import main
from cairnkit.paths import current_branch, writer_name


def stop_in_a_rebase(repo):
    (repo / "a.txt").write_text("base\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-qm", "base")
    git(repo, "switch", "-qc", "rb")
    (repo / "a.txt").write_text("rb\n")
    git(repo, "commit", "-qam", "rb")
    git(repo, "switch", "-q", "main")
    (repo / "a.txt").write_text("main\n")
    git(repo, "commit", "-qam", "main")
    git(repo, "switch", "-q", "rb")
    result = subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0, "the rebase must stop at a conflict"


def finish_the_rebase(repo):
    git(repo, "checkout", "--theirs", "a.txt")
    git(repo, "add", "a.txt")
    subprocess.run(
        ["git", "-c", "core.editor=true", "rebase", "--continue"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def load(capsys):
    capsys.readouterr()
    assert main(["load"]) == 0
    return capsys.readouterr().out


def test_short_note_from_a_rebase_loads_on_its_branch(repo, mem, capsys):
    stop_in_a_rebase(repo)
    assert main(["add", "conflict in a.txt", "--short"]) == 0
    assert "detached HEAD" not in capsys.readouterr().out
    assert "conflict in a.txt" in load(capsys)
    finish_the_rebase(repo)
    assert git(repo, "branch", "--show-current").strip() == "rb"
    assert "conflict in a.txt" in load(capsys)
    git(repo, "switch", "-q", "main")
    assert "conflict in a.txt" not in load(capsys)


def test_writer_during_a_rebase_is_the_branch(repo, mem):
    stop_in_a_rebase(repo)
    assert current_branch(repo) == "rb"
    assert writer_name(repo) == "rb"
    assert (mem / "facts").is_dir()


def test_plain_detached_head_has_no_branch(repo):
    git(repo, "checkout", "-q", "--detach")
    assert current_branch(repo) is None
    assert writer_name(repo) == "main"


def test_a_rebase_of_a_detached_head_has_no_branch(repo):
    stop_in_a_rebase(repo)
    subprocess.run(["git", "rebase", "--abort"], cwd=repo, check=True, capture_output=True)
    git(repo, "checkout", "-q", "--detach", "rb")
    result = subprocess.run(["git", "rebase", "main"], cwd=repo, capture_output=True, text=True)
    assert result.returncode != 0
    assert current_branch(repo) is None
