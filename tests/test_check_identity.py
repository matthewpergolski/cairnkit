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


# Owner login is a flag, not a banlist. The positive fixture uses the real
# GitHub squash shape from merges onto main (id+login noreply).
OWNER = "matthewpergolski"
OWNER_DISPLAY = "Matthew L. Pergolski"
OWNER_EMAIL = f"160999621+{OWNER}@users.noreply.github.com"
OTHER_EMAIL = "999999+other-contributor@users.noreply.github.com"
GITHUB_NAME = "GitHub"
GITHUB_EMAIL = "noreply@github.com"


def _squash_env(*, email: str = OWNER_EMAIL, name: str = OWNER_DISPLAY) -> dict[str, str]:
    return {
        **dict(__import__("os").environ),
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": GITHUB_NAME,
        "GIT_COMMITTER_EMAIL": GITHUB_EMAIL,
    }


def test_github_squash_is_rejected_without_allow_flag(mod, tmp_path):
    repo = init_repo(tmp_path / "squash-default")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "Add a thing (#14)", env=_squash_env())
    errors = mod.check_range(repo, "HEAD~1..HEAD")
    assert errors
    assert any("committer" in e.lower() and GITHUB_EMAIL in e for e in errors)


def test_github_squash_is_accepted_with_allow_flag(mod, tmp_path):
    """Push mode: real squash shape (owner noreply + GitHub + (#N)) is clean."""
    repo = init_repo(tmp_path / "squash-ok")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "Add a thing (#14)", env=_squash_env())
    assert mod.check_range(repo, "HEAD~1..HEAD", allow_github_squash=True, owner=OWNER) == []


def test_github_squash_still_rejects_ai_trailer(mod, tmp_path):
    repo = init_repo(tmp_path / "squash-ai")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    msg = "Add a thing (#14)\n\nCo-authored-by: Claude <noreply@anthropic.com>\n"
    git(repo, "commit", "-q", "-m", msg, env=_squash_env())
    errors = mod.check_range(repo, "HEAD~1..HEAD", allow_github_squash=True, owner=OWNER)
    assert any("co-authored-by" in e.lower() for e in errors)


def test_github_squash_rejects_non_owner_author(mod, tmp_path):
    repo = init_repo(tmp_path / "squash-other")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    git(
        repo,
        "commit",
        "-q",
        "-m",
        "Add a thing (#14)",
        env=_squash_env(email=OTHER_EMAIL, name="Other Contributor"),
    )
    errors = mod.check_range(repo, "HEAD~1..HEAD", allow_github_squash=True, owner=OWNER)
    assert errors
    assert any("author" in e.lower() and "other-contributor" in e for e in errors)


def test_github_squash_requires_pr_number_in_subject(mod, tmp_path):
    repo = init_repo(tmp_path / "squash-no-pr")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "Add a thing without a PR ref", env=_squash_env())
    errors = mod.check_range(repo, "HEAD~1..HEAD", allow_github_squash=True, owner=OWNER)
    assert errors


def test_cli_allow_github_squash_flag(mod, tmp_path):
    repo = init_repo(tmp_path / "squash-cli")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "Land feature (#99)", env=_squash_env())
    ok = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--allow-github-squash",
            f"--owner={OWNER}",
            "HEAD~1..HEAD",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert ok.returncode == 0, ok.stderr


def test_simulate_squash_passes_push_mode_check(mod, tmp_path):
    """PR CI builds a fake squash (owner + GitHub + title (#N)) and checks it."""
    repo = init_repo(tmp_path / "sim-ok")
    (repo / "a.txt").write_text("feature\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "feature work")
    sha = mod.simulate_github_squash(
        repo,
        owner=OWNER,
        pr_number=42,
        title="Land the feature",
        body="Why it exists.\n",
        author_name=OWNER_DISPLAY,
        author_email=OWNER_EMAIL,
    )
    assert mod.check_range(repo, f"{sha}^!", allow_github_squash=True, owner=OWNER) == []


def test_simulate_squash_with_ai_trailer_fails_push_mode(mod, tmp_path):
    repo = init_repo(tmp_path / "sim-ai")
    (repo / "a.txt").write_text("feature\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "feature work")
    sha = mod.simulate_github_squash(
        repo,
        owner=OWNER,
        pr_number=7,
        title="Land the feature",
        body="Notes.\n\nCo-authored-by: Claude <noreply@anthropic.com>\n",
        author_name=OWNER_DISPLAY,
        author_email=OWNER_EMAIL,
    )
    errors = mod.check_range(repo, f"{sha}^!", allow_github_squash=True, owner=OWNER)
    assert any("co-authored-by" in e.lower() for e in errors)


def test_cli_check_simulated_squash(mod, tmp_path):
    repo = init_repo(tmp_path / "sim-cli")
    (repo / "a.txt").write_text("x\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "work")
    body = repo / "body.md"
    body.write_text("Summary of the change.\n")
    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--check-simulated-squash",
            f"--owner={OWNER}",
            "--pr-number=15",
            "--title=Ship it",
            "--author-name",
            OWNER_DISPLAY,
            "--author-email",
            OWNER_EMAIL,
            "--body-file",
            str(body),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_github_system_emails_in_docs_are_allowed(mod, tmp_path):
    """Docs may name GitHub's squash committer and users.noreply forms."""
    repo = init_repo(tmp_path / "gh-docs")
    (repo / "note.md").write_text(
        "Squash committer is GitHub <noreply@github.com>.\n"
        "Owner mail looks like owner@users.noreply.github.com.\n"
        f"Real shape: {OWNER_EMAIL}\n"
    )
    git(repo, "add", "note.md")
    git(repo, "commit", "-q", "-m", "document squash identity")
    assert mod.check_range(repo, "HEAD~1..HEAD") == []
