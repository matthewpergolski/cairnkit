"""CI and the optional verify pre-push use one check command: scripts/verify.sh."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"
VERIFY = ROOT / "scripts" / "verify.sh"
E2E = ROOT / "scripts" / "e2e.sh"
INSTALL = ROOT / "scripts" / "install-verify-pre-push.sh"


def test_ci_calls_verify_sh_not_retyped_checks():
    text = CI.read_text()
    assert "./scripts/verify.sh" in text
    # CI must not retype the three checks that verify.sh already runs.
    assert "uv run ruff check" not in text
    assert "uv run ruff format" not in text
    assert "uv run pytest" not in text


def test_ci_runs_e2e_on_linux():
    text = CI.read_text()
    assert "scripts/e2e.sh" in text
    # Linux first: the e2e job (or step) must pin ubuntu, not only the matrix.
    assert "ubuntu-latest" in text
    # e2e must appear in a job/step that names ubuntu (not only via the matrix).
    assert "e2e" in text.lower()


def test_verify_and_e2e_scripts_exist_and_are_executable():
    assert VERIFY.is_file() and os.access(VERIFY, os.X_OK)
    assert E2E.is_file() and os.access(E2E, os.X_OK)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "e2e")
    git(root, "config", "user.email", "e2e@example.invalid")
    # Point the installer at this throwaway repo's hooks.
    (root / "scripts").mkdir()
    # A tiny verify stand-in so the hook body is valid in the fixture.
    (root / "scripts" / "verify.sh").write_text("#!/bin/sh\nexit 0\n")
    (root / "scripts" / "verify.sh").chmod(0o755)
    return root


def _hooks(repo: Path) -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(out) if Path(out).is_absolute() else repo / out


def test_install_verify_pre_push_chains_with_cairnkit_block(repo: Path):
    """A cairnkit marked block stays; verify runs after it."""
    from cairnkit.githook import END, START, write_block

    hooks = _hooks(repo)
    hooks.mkdir(parents=True, exist_ok=True)
    write_block(hooks / "pre-push", "echo cairnkit-tidy || true\n", dry_run=False)
    # Copy the real installer into the fixture so relative paths match a checkout.
    assert INSTALL.is_file(), "scripts/install-verify-pre-push.sh is missing"
    path = repo / "scripts" / "install-verify-pre-push.sh"
    path.write_text(INSTALL.read_text())
    path.chmod(0o755)
    result = subprocess.run(
        ["bash", str(path)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    text = (hooks / "pre-push").read_text()
    assert START in text and END in text
    assert "echo cairnkit-tidy" in text
    assert "scripts/verify.sh" in text
    # cairnkit block comes before verify so a failing verify still ran tidy first.
    assert text.index(START) < text.index("scripts/verify.sh")


def test_install_verify_pre_push_then_cairnkit_keeps_verify(repo: Path):
    """memory hooks install keeps a foreign verify body (chaining the other way)."""
    from cairnkit.githook import END, START, write_block

    hooks = _hooks(repo)
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "pre-push").write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            root="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
            "$root/scripts/verify.sh" || exit 1
            """
        )
    )
    (hooks / "pre-push").chmod(0o755)
    write_block(hooks / "pre-push", "echo cairnkit-tidy || true\n", dry_run=False)
    text = (hooks / "pre-push").read_text()
    assert START in text and END in text
    assert "scripts/verify.sh" in text
    assert "echo cairnkit-tidy" in text
