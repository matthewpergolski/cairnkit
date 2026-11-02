from __future__ import annotations

import subprocess
import sys
import time

import pytest
from conftest import assert_marker_gone, git, hung_marker, write_hung_interpreter

from cairnkit.cli import main

CLASH = "error: --check cannot be combined with --dry-run or --force\n"


def state_dir(repo):
    return repo / "docs" / "state"


def plant_cairnkit_atlas_sources(repo) -> None:
    """Make the throwaway repo classify as cairnkit so session/lifecycle pages exist."""
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "cairnkit"\nversion = "0.3.0"\n'
        'description = "A private, dated memory for any project."\n',
        encoding="utf-8",
    )
    folder = repo / "src" / "cairnkit"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "__init__.py").write_text("", encoding="utf-8")
    for name in ("cli", "hookrun", "load", "schema", "state", "store", "memory", "docs_cmd"):
        (folder / f"{name}.py").write_text(f"# {name}\n", encoding="utf-8")


def edit_body(page) -> str:
    """An edit that leaves the page's front matter as the tool wrote it."""
    text = page.read_text(encoding="utf-8") + "an edit\n"
    page.write_text(text, encoding="utf-8")
    return text


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
    plant_cairnkit_atlas_sources(repo)
    assert main(["docs", "--force"]) == 0
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
    plant_cairnkit_atlas_sources(repo)
    assert main(["docs", "--force"]) == 0
    life = state_dir(repo) / "fact-lifecycle.md"
    edited = edit_body(life)
    orphan = state_dir(repo) / "services" / "orphan.md"
    orphan.parent.mkdir()
    orphan.write_text(edited, encoding="utf-8")
    capsys.readouterr()
    code = main(["docs", "--check"])
    out = capsys.readouterr()
    assert code == 1
    assert out.err == ""
    assert out.out == ("docs/state/fact-lifecycle.md\ndocs/state/services/orphan.md\n")
    assert life.read_text(encoding="utf-8") == edited
    assert orphan.read_text(encoding="utf-8") == edited


def test_check_sorts_readme_before_lowercase_names(mem, repo, capsys):
    plant_cairnkit_atlas_sources(repo)
    assert main(["docs", "--force"]) == 0
    for name in ("README.md", "fact-lifecycle.md"):
        edit_body(state_dir(repo) / name)
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


def _install_post_merge(repo, capsys):
    capsys.readouterr()
    assert main(["hooks", "install", "--agent", "generic"]) == 0
    return repo / ".git" / "hooks" / "post-merge"


def _run_hook(hook, repo, env=None):
    return subprocess.run(
        ["sh", str(hook)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_hook_post_merge_does_not_print_the_docs_line(mem, repo, capsys):
    assert main(["docs"]) == 0
    readme = state_dir(repo) / "README.md"
    readme.write_text("stale\n", encoding="utf-8")
    capsys.readouterr()
    code = main(["hook", "post-merge"])
    out = capsys.readouterr()
    assert code == 0
    assert out.out == ""
    assert out.err == ""
    assert readme.read_text(encoding="utf-8") == "stale\n"


def test_installed_post_merge_is_silent_when_current(mem, repo, capsys):
    assert main(["docs"]) == 0
    hook = _install_post_merge(repo, capsys)
    result = _run_hook(hook, repo)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_installed_post_merge_is_silent_without_state(mem, repo, capsys):
    hook = _install_post_merge(repo, capsys)
    result = _run_hook(hook, repo)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert not state_dir(repo).exists()


def test_post_merge_stays_silent_when_cairnkit_is_missing(repo, capsys):
    state = state_dir(repo)
    state.mkdir(parents=True)
    (state / "README.md").write_text("old\n", encoding="utf-8")
    hook = _install_post_merge(repo, capsys)
    py = "/usr/bin/python3"
    assert py != sys.executable
    probe = subprocess.run([py, "-c", "import cairnkit"], capture_output=True, text=True)
    assert probe.returncode != 0
    hook.write_text(hook.read_text().replace(sys.executable, py))
    result = _run_hook(hook, repo)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert "No module named" not in result.stderr


def test_hung_post_merge_stays_quiet_and_finishes(repo, capsys, tmp_path):
    state = state_dir(repo)
    state.mkdir(parents=True)
    (state / "README.md").write_text("stale\n", encoding="utf-8")
    hook = _install_post_merge(repo, capsys)
    marker = hung_marker()
    fake = tmp_path / "hung-python"
    write_hung_interpreter(fake, marker)
    hook.write_text(hook.read_text().replace(sys.executable, str(fake)))
    began = time.monotonic()
    result = _run_hook(hook, repo)
    elapsed = time.monotonic() - began
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert elapsed < 8, f"hung interpreter stalled post-merge for {elapsed:.1f}s"
    assert_marker_gone(marker)


def _stale_atlas(repo):
    assert main(["docs"]) == 0
    readme = state_dir(repo) / "README.md"
    return readme, edit_body(readme)


def test_a_real_merge_says_nothing_about_a_stale_atlas(mem, repo, capsys):
    readme, edited = _stale_atlas(repo)
    _install_post_merge(repo, capsys)
    git(repo, "checkout", "-q", "-b", "topic")
    (repo / "topic.txt").write_text("t\n", encoding="utf-8")
    git(repo, "add", "topic.txt")
    git(repo, "commit", "-q", "-m", "topic")
    git(repo, "checkout", "-q", "main")
    result = subprocess.run(
        ["git", "merge", "--no-ff", "-m", "merge topic", "topic"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "docs/state" not in result.stdout + result.stderr
    assert "cairnkit" not in result.stdout + result.stderr
    assert readme.read_text(encoding="utf-8") == edited


def test_status_says_what_force_writes_when_the_atlas_is_stale(mem, repo, capsys):
    readme, edited = _stale_atlas(repo)
    capsys.readouterr()
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    line = next(item for item in out.splitlines() if "docs/state" in item)
    assert "1 page" in line
    assert "memory docs --force" in line
    assert "no model and no network" in line
    assert "tracked" in line
    assert readme.read_text(encoding="utf-8") == edited


def test_status_is_silent_about_a_current_or_absent_atlas(mem, repo, capsys):
    capsys.readouterr()
    assert main(["status"]) == 0
    assert "docs/state" not in capsys.readouterr().out
    assert main(["docs"]) == 0
    capsys.readouterr()
    assert main(["status"]) == 0
    assert "docs/state" not in capsys.readouterr().out


def test_status_still_works_when_the_atlas_cannot_be_read(mem, repo, capsys, monkeypatch):
    from cairnkit import docs_cmd

    _stale_atlas(repo)

    def broken(project):
        raise OSError("no")

    monkeypatch.setattr(docs_cmd, "build_atlas", broken)
    capsys.readouterr()
    assert main(["status"]) == 0
    assert "docs/state" not in capsys.readouterr().out
