"""`memory docs --check` and the post-merge freshness line.

Both callers share one comparison. The check is a gate. The hook is a courtesy
that never fails git and never writes.
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest
from conftest import git

from cairnkit import githook
from cairnkit.cli import main

STALE_LINE = "cairnkit: docs/state looks out of date; run memory docs --force"
CLASH = "error: --check cannot be combined with --dry-run or --force\n"


def state_dir(repo):
    return repo / "docs" / "state"


def _hook_lines(text: str, event: str) -> list[str]:
    return [line for line in text.splitlines() if f"hook {event}" in line]


def _discards_stdout(line: str) -> bool:
    """True when this command sends stdout to /dev/null (not stderr alone)."""
    return re.search(r"(?<![0-9])>/dev/null", line) is not None


def _split_post_merge(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    cut = next(i for i, line in enumerate(lines) if "hook post-merge" in line)
    return "".join(lines[:cut]), "".join(lines[cut:])


def test_stale_paths_are_a_sorted_unique_tuple():
    from cairnkit.docs_cmd import Stale

    with pytest.raises(ValueError):
        Stale(())
    with pytest.raises(ValueError):
        Stale(("docs/state/b.md", "docs/state/a.md"))
    with pytest.raises(ValueError):
        Stale(("docs/state/a.md", "docs/state/a.md"))
    assert Stale(("docs/state/a.md", "docs/state/b.md")).changed == (
        "docs/state/a.md",
        "docs/state/b.md",
    )


def test_check_is_quiet_without_an_atlas(repo, capsys):
    sibling = repo.parent / f"{repo.name}.memory"
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert not state_dir(repo).exists()
    assert not sibling.exists()


def test_check_is_quiet_without_an_atlas_after_init(mem, repo, capsys):
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert not state_dir(repo).exists()


def test_check_is_quiet_when_state_has_no_markdown(repo, capsys):
    state = state_dir(repo)
    state.mkdir(parents=True)
    note = state / "notes.txt"
    note.write_text("not a page\n", encoding="utf-8")
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert note.read_text(encoding="utf-8") == "not a page\n"


def test_check_is_quiet_when_state_path_is_a_file(repo, capsys):
    (repo / "docs").mkdir()
    (repo / "docs" / "state").write_text("nope\n", encoding="utf-8")
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert (repo / "docs" / "state").read_text(encoding="utf-8") == "nope\n"


def test_check_ignores_path_and_does_not_open_memory(repo, capsys):
    code = main(["docs", "--check", "--path", "/no/such/memory"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert not state_dir(repo).exists()


def test_check_is_quiet_when_current(mem, repo, capsys):
    assert main(["docs"]) == 0
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""


def test_check_ignores_source_revision_when_head_moves(mem, repo, capsys):
    assert main(["docs"]) == 0
    git(repo, "add", "docs")
    git(repo, "commit", "-q", "-m", "atlas")
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""


def test_check_reports_a_body_edit(mem, repo, capsys):
    assert main(["docs"]) == 0
    readme = state_dir(repo) / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "Nessa Docs" in text
    readme.write_text(text.replace("Nessa Docs", "Nessa Docz", 1), encoding="utf-8")
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 1
    assert out.err == ""
    assert out.out == "docs/state/README.md\n"
    assert "Nessa Docz" in readme.read_text(encoding="utf-8")


def test_check_lists_a_missing_page(mem, repo, capsys):
    assert main(["docs"]) == 0
    page = state_dir(repo) / "agent-session.md"
    page.unlink()
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 1
    assert out.err == ""
    assert out.out == "docs/state/agent-session.md\n"
    assert not page.exists()


def test_check_lists_changed_and_orphan_pages(mem, repo, capsys):
    assert main(["docs"]) == 0
    life = state_dir(repo) / "fact-lifecycle.md"
    life.write_text("nope\n", encoding="utf-8")
    orphan = state_dir(repo) / "services" / "orphan.md"
    orphan.parent.mkdir()
    orphan.write_text("extra\n", encoding="utf-8")
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 1
    assert out.err == ""
    assert out.out == ("docs/state/fact-lifecycle.md\ndocs/state/services/orphan.md\n")
    assert life.read_text(encoding="utf-8") == "nope\n"
    assert orphan.read_text(encoding="utf-8") == "extra\n"


def test_check_sorts_readme_before_lowercase_names(mem, repo, capsys):
    assert main(["docs"]) == 0
    for name in ("README.md", "fact-lifecycle.md"):
        (state_dir(repo) / name).write_text("nope\n", encoding="utf-8")
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 1
    assert out.out == "docs/state/README.md\ndocs/state/fact-lifecycle.md\n"


def test_check_ignores_non_markdown_beside_pages(mem, repo, capsys):
    assert main(["docs"]) == 0
    note = state_dir(repo) / "notes.txt"
    note.write_text("x\n", encoding="utf-8")
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert note.read_text(encoding="utf-8") == "x\n"


def test_check_treats_a_markdown_directory_as_stale(mem, repo, capsys):
    assert main(["docs"]) == 0
    page = state_dir(repo) / "agent-session.md"
    page.unlink()
    page.mkdir()
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 1
    assert out.err == ""
    assert out.out == "docs/state/agent-session.md\n"
    assert page.is_dir()


@pytest.mark.parametrize("extra", [["--force"], ["--dry-run"], ["--force", "--dry-run"]])
def test_check_refuses_force_and_dry_run(mem, repo, capsys, extra):
    assert main(["docs"]) == 0
    readme = state_dir(repo) / "README.md"
    readme.write_text("stale\n", encoding="utf-8")
    capsys.readouterr()
    code = main(["docs", "--check", *extra])
    out = capsys.readouterr()
    assert code == 1
    assert out.out == ""
    assert out.err == CLASH
    assert readme.read_text(encoding="utf-8") == "stale\n"


@pytest.mark.parametrize("extra", [["--force"], ["--dry-run"]])
def test_check_clash_does_not_create_state(repo, capsys, extra):
    code = main(["docs", "--check", *extra])
    out = capsys.readouterr()
    assert code == 1
    assert out.out == ""
    assert out.err == CLASH
    assert not state_dir(repo).exists()


def test_force_dry_run_still_previews(mem, repo, capsys):
    assert main(["docs"]) == 0
    readme = state_dir(repo) / "README.md"
    before = readme.read_text(encoding="utf-8")
    capsys.readouterr()
    code = main(["docs", "--force", "--dry-run"])
    out = capsys.readouterr()
    assert code == 0
    assert "Would write" in out.out
    assert readme.read_text(encoding="utf-8") == before


def test_docs_freshness_warns_without_reading_stdin(mem, repo):
    assert main(["docs"]) == 0
    readme = state_dir(repo) / "README.md"
    readme.write_text("stale\n", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "cairnkit", "hook", "docs-freshness"],
        cwd=repo,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        raise
    out, err = proc.communicate()
    assert proc.returncode == 0
    assert out == STALE_LINE + "\n"
    assert err == ""
    assert readme.read_text(encoding="utf-8") == "stale\n"


def test_docs_freshness_is_silent_when_current(mem, repo, capsys):
    assert main(["docs"]) == 0
    capsys.readouterr()
    code = main(["hook", "docs-freshness"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""


def test_docs_freshness_is_silent_when_absent(mem, repo, capsys):
    capsys.readouterr()
    code = main(["hook", "docs-freshness"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert not state_dir(repo).exists()


@pytest.mark.parametrize("boom", [RuntimeError("boom"), SystemExit(7)])
def test_docs_freshness_stays_quiet_when_the_compare_crashes(mem, repo, monkeypatch, capsys, boom):
    assert main(["docs"]) == 0
    readme = state_dir(repo) / "README.md"
    before = readme.read_text(encoding="utf-8")

    def raise_boom(_project):
        raise boom

    monkeypatch.setattr("cairnkit.docs_cmd.atlas_freshness", raise_boom)
    capsys.readouterr()
    code = main(["hook", "docs-freshness"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert readme.read_text(encoding="utf-8") == before


def test_post_merge_body_speaks_then_stays_quiet():
    text = githook.post_merge_body()
    fresh, quiet = _split_post_merge(text)
    fresh_cmds = _hook_lines(fresh, "docs-freshness")
    quiet_cmds = _hook_lines(quiet, "post-merge")
    assert fresh_cmds and quiet_cmds
    assert "[ -d docs/state ]" in fresh
    assert all("2>/dev/null" in line and not _discards_stdout(line) for line in fresh_cmds)
    assert "timeout -k 1 1 " in fresh
    assert "looks out of date" not in text
    assert all(_discards_stdout(line) for line in quiet_cmds)
    assert "timeout -k 1 3 " in quiet
    assert fresh.count("|| true") == quiet.count("|| true") >= 1
    assert "docs-freshness" not in githook.pre_push_body()
    assert "docs-freshness" not in githook.post_commit_body()
    assert "docs-freshness" not in githook.post_checkout_body(False)
    assert "docs-freshness" not in githook.post_checkout_body(True)


def test_merge_prints_one_stale_line_and_succeeds(mem, repo, capsys):
    assert main(["docs"]) == 0
    readme = state_dir(repo) / "README.md"
    readme.write_text("stale\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    git(repo, "checkout", "-q", "-b", "topic")
    (repo / "topic.txt").write_text("t\n", encoding="utf-8")
    git(repo, "add", "topic.txt")
    git(repo, "commit", "-q", "-m", "topic")
    git(repo, "checkout", "-q", "main")
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=.git/hooks",
            "merge",
            "--no-ff",
            "-m",
            "merge topic",
            "topic",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # Git delivers hook stdout on the git command's stderr.
    said = [line for line in result.stderr.splitlines() if line.startswith("cairnkit:")]
    assert said == [STALE_LINE]
    assert STALE_LINE not in result.stdout
    assert readme.read_text(encoding="utf-8") == "stale\n"
