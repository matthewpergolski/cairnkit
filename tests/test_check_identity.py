"""scripts/check_identity.py: only the neutral cairnkit identity may land."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_identity.py"

NEUTRAL_NAME = "cairnkit contributors"
NEUTRAL_EMAIL = "cairnkit@users.noreply.github.com"


def load_mod():
    spec = importlib.util.spec_from_file_location("check_identity", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return load_mod()


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return result.stdout


def init_repo(path: Path, *, name: str = NEUTRAL_NAME, email: str = NEUTRAL_EMAIL) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", name)
    git(path, "config", "user.email", email)
    (path / "README.md").write_text("start\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "start")
    return path


def test_neutral_range_is_clean(mod, tmp_path):
    repo = init_repo(tmp_path / "ok")
    (repo / "a.txt").write_text("ok\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "add a")
    assert mod.check_range(repo, "HEAD~1..HEAD") == []


def test_foreign_author_email_is_reported(mod, tmp_path):
    repo = init_repo(tmp_path / "bad-author")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    env = {
        **{k: v for k, v in __import__("os").environ.items() if k not in ("GIT_AUTHOR_EMAIL",)},
        "GIT_AUTHOR_NAME": NEUTRAL_NAME,
        "GIT_AUTHOR_EMAIL": "stranger@example.net",
        "GIT_COMMITTER_NAME": NEUTRAL_NAME,
        "GIT_COMMITTER_EMAIL": NEUTRAL_EMAIL,
    }
    git(repo, "commit", "-q", "-m", "bad author", env=env)
    errors = mod.check_range(repo, "HEAD~1..HEAD")
    assert errors
    assert any("author" in e.lower() and "stranger@example.net" in e for e in errors)


def test_foreign_committer_email_is_reported(mod, tmp_path):
    repo = init_repo(tmp_path / "bad-committer")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    env = {
        **dict(__import__("os").environ),
        "GIT_AUTHOR_NAME": NEUTRAL_NAME,
        "GIT_AUTHOR_EMAIL": NEUTRAL_EMAIL,
        "GIT_COMMITTER_NAME": NEUTRAL_NAME,
        "GIT_COMMITTER_EMAIL": "other@example.net",
    }
    git(repo, "commit", "-q", "-m", "bad committer", env=env)
    errors = mod.check_range(repo, "HEAD~1..HEAD")
    assert any("committer" in e.lower() and "other@example.net" in e for e in errors)


def test_foreign_co_authored_by_trailer_is_reported(mod, tmp_path):
    repo = init_repo(tmp_path / "trailer")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    msg = "feat\n\nCo-authored-by: Someone Else <else@example.net>\n"
    git(repo, "commit", "-q", "-m", msg)
    errors = mod.check_range(repo, "HEAD~1..HEAD")
    assert any("co-authored-by" in e.lower() and "else@example.net" in e for e in errors)


def test_foreign_signed_off_by_trailer_is_reported(mod, tmp_path):
    repo = init_repo(tmp_path / "sob")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    msg = "feat\n\nSigned-off-by: Someone Else <else@example.net>\n"
    git(repo, "commit", "-q", "-m", msg)
    errors = mod.check_range(repo, "HEAD~1..HEAD")
    assert any("signed-off-by" in e.lower() and "else@example.net" in e for e in errors)


def test_added_personal_email_in_file_is_reported(mod, tmp_path):
    # Build the address at runtime so this test file itself stays clean under
    # the identity check (no personal-looking literal in added lines).
    addr = "person@" + "somewhere.org"
    repo = init_repo(tmp_path / "file-email")
    (repo / "note.md").write_text(f"contact me at {addr} please\n")
    git(repo, "add", "note.md")
    git(repo, "commit", "-q", "-m", "add note")
    errors = mod.check_range(repo, "HEAD~1..HEAD")
    assert any(addr in e for e in errors)


def test_generic_example_emails_in_files_are_allowed(mod, tmp_path):
    repo = init_repo(tmp_path / "generic")
    (repo / "note.md").write_text(
        f"neutral {NEUTRAL_EMAIL}\n"
        "clone git@github.com:org/repo.git\n"
        "tests use test@example.invalid\n"
    )
    git(repo, "add", "note.md")
    git(repo, "commit", "-q", "-m", "generic examples")
    assert mod.check_range(repo, "HEAD~1..HEAD") == []


def test_personal_email_under_tests_path_is_allowed(mod, tmp_path):
    addr = "person@" + "somewhere.org"
    repo = init_repo(tmp_path / "tests-dir")
    (repo / "tests").mkdir()
    (repo / "tests" / "fixture.txt").write_text(f"{addr}\n")
    git(repo, "add", "tests/fixture.txt")
    git(repo, "commit", "-q", "-m", "fixture under tests")
    assert mod.check_range(repo, "HEAD~1..HEAD") == []


def test_cli_exits_1_on_bad_range(mod, tmp_path):
    repo = init_repo(tmp_path / "cli")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    env = {
        **dict(__import__("os").environ),
        "GIT_AUTHOR_NAME": "Nope",
        "GIT_AUTHOR_EMAIL": "nope@example.net",
        "GIT_COMMITTER_NAME": NEUTRAL_NAME,
        "GIT_COMMITTER_EMAIL": NEUTRAL_EMAIL,
    }
    git(repo, "commit", "-q", "-m", "bad", env=env)
    code = subprocess.run(
        ["python3", str(SCRIPT), "HEAD~1..HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
    ).returncode
    assert code == 1
