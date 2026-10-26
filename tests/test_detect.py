"""Toolchain detection for preset rules with `when` and `enforce_when`.

A rule is enforced only when a hook or CI runs its check. The dev preset has no
rule for one tool, so most tests use the `tools` test preset (fixtures/tools_preset.toml).
"""

import shutil
from pathlib import Path

import pytest
from conftest import DEV_KEYS, FIXTURES, add_worktree, git, read_jsonl

from cairnkit import detect as detection
from cairnkit import presets
from cairnkit.cli import main

PUSH_CHECK = """\
def checks():
    return [
        ("Python lint", ["uv", "run", "ruff", "check", "."]),
        ("JavaScript lint", ["sh", "-c", "npx --yes @biomejs/biome lint tests/*.mjs"]),
    ]
"""


def write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def hook(root: Path, rel: str, text: str, executable: bool = True) -> None:
    write(root, rel, text)
    (root / rel).chmod(0o755 if executable else 0o644)


def web_app_like(root: Path) -> None:
    """A repo like a small web app: Python backend, Bun frontend, a pre-push hook."""
    write(root, "pyproject.toml", '[dependency-groups]\ndev = ["ruff>=0.16"]\n')
    write(root, "uv.lock", "version = 1\n")
    write(root, ".python-version", "3.14\n")
    write(root, "backend/pyproject.toml", '[project]\nname = "b"\n\n[tool.ruff]\nsrc = ["."]\n')
    write(root, "frontend/package.json", '{"scripts": {"lint": "biome check src"}}\n')
    write(root, "frontend/bun.lock", "{}\n")
    write(root, "frontend/biome.json", "{}\n")
    write(root, "frontend/.bun-version", "1.4.3\n")
    write(root, "frontend/node_modules/x/package-lock.json", "{}\n")
    hook(root, ".githooks/pre-push", "#!/bin/sh\nexec uv run tools/push_check.py\n")
    write(root, "tools/push_check.py", PUSH_CHECK)
    git(root, "config", "core.hooksPath", ".githooks")


def rules_by_key(repo: Path) -> dict[str, dict]:
    path = repo.parent / "proj.memory" / "facts" / "default.jsonl"
    return {r["preset_rule"]: r for r in read_jsonl(path) if r["type"] == "fact"}


def run(capsys, *args) -> tuple[int, str]:
    capsys.readouterr()
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out + out.err


@pytest.fixture
def tools_preset(tmp_path, monkeypatch):
    """The shipped presets plus the `tools` test preset."""
    data = tmp_path / "preset_data"
    shutil.copytree(presets.DATA, data)
    shutil.copy(FIXTURES / "tools_preset.toml", data / "tools.toml")
    monkeypatch.setattr(presets, "DATA", data)


def test_detect_uv_ruff_bun_biome_pins_from_fixture_repo(repo):
    web_app_like(repo)
    found = detection.detect(repo)
    assert set(found) == set(detection.NAMES)
    for name in ("uv", "ruff", "ruff-run", "bun", "biome", "biome-run", "pins"):
        assert found[name].found, name
    assert not found["other-lockfile"].found
    assert "backend/pyproject.toml" in found["ruff"].reason
    assert ".githooks/pre-push -> tools/push_check.py" in found["ruff-run"].reason
    assert "frontend/bun.lock" in found["bun"].reason
    assert ".python-version" in found["pins"].reason
    assert "frontend/.bun-version" in found["pins"].reason


def test_init_tools_on_web_app_like_repo_enforces_ruff_and_biome(repo, capsys, tools_preset):
    web_app_like(repo)
    code, out = run(capsys, "init", "--preset", "dev", "--preset", "tools")
    assert code == 0
    rules = rules_by_key(repo)
    assert rules["tools.ruff"]["enforced_by"] == "lint:ruff"
    assert rules["tools.biome"]["enforced_by"] == "lint:biome"
    assert "enforced_by" not in rules["tools.uv"]
    assert {"tools.uv", "tools.bun", "tools.pins"} <= set(rules)
    assert "dev.lockfile" not in rules
    assert "tools.ruff: enforced by lint:ruff (" in out
    assert "dev.lockfile: not detected" in out


def test_init_dev_adds_no_single_tool_rules(repo, capsys):
    web_app_like(repo)
    code, out = run(capsys, "init", "--preset", "dev")
    assert code == 0
    rules = rules_by_key(repo)
    assert set(rules) == DEV_KEYS - {"dev.lockfile"}
    assert all("enforced_by" not in r for r in rules.values())
    assert "dev.ruff" not in out and "dev.uv" not in out


def test_ruff_rule_enforced_only_when_run_by_hook_or_ci(repo, capsys, tools_preset):
    write(repo, "pyproject.toml", '[project]\nname = "x"\n\n[tool.ruff]\nline-length = 100\n')
    write(repo, "scripts/verify.sh", "uv run ruff check .\n")
    code, out = run(capsys, "preset", "show", "tools", "--detect")
    assert code == 0
    assert "+ tools.ruff: advisory (ruff config in pyproject.toml; no hook or CI runs ruff)" in out
    workflow = "jobs:\n  lint:\n    steps:\n      - run: ./scripts/verify.sh\n"
    write(repo, ".github/workflows/ci.yml", workflow)
    code, out = run(capsys, "preset", "show", "tools", "--detect")
    assert "+ tools.ruff: enforced by lint:ruff" in out
    assert ".github/workflows/ci.yml -> scripts/verify.sh" in out
    assert main(["init", "--preset", "tools"]) == 0
    assert rules_by_key(repo)["tools.ruff"]["enforced_by"] == "lint:ruff"


def test_biome_run_through_a_package_script(repo):
    write(repo, "biome.json", "{}\n")
    write(repo, "package.json", '{"scripts": {"lint": "biome check src", "test": "bun test"}}\n')
    write(repo, "bun.lock", "{}\n")
    write(repo, ".husky/pre-commit", "bun run lint\n")
    assert not detection.detect(repo)["biome-run"].found
    git(repo, "config", "core.hooksPath", ".husky/_")
    found = detection.detect(repo)
    assert found["biome-run"].found
    assert ".husky/pre-commit -> package.json script lint" in found["biome-run"].reason


def test_no_toolchain_detected_gives_neutral_rules_only(repo, capsys):
    assert main(["init", "--preset", "dev"]) == 0
    got = set(rules_by_key(repo))
    assert "dev.lockfile" not in got
    assert {"dev.verify", "dev.tests", "dev.git"} <= got
    assert all("enforced_by" not in r for r in rules_by_key(repo).values())


def test_other_lock_file_gives_the_neutral_package_manager_rule(repo):
    write(repo, "package.json", "{}\n")
    write(repo, "package-lock.json", "{}\n")
    assert main(["init", "--preset", "dev"]) == 0
    got = set(rules_by_key(repo))
    assert "dev.lockfile" in got and "dev.bun" not in got


def test_preset_list_and_show_detect_output(repo, capsys, tools_preset):
    web_app_like(repo)
    code, out = run(capsys, "preset", "list")
    assert code == 0 and "dev" in out and "basic" in out
    code, out = run(capsys, "preset", "show", "dev", "--detect")
    assert code == 0
    assert f"Detected in {repo}" in out
    assert "- dev.lockfile: not detected" in out
    code, out = run(capsys, "preset", "show", "tools", "--detect")
    assert "+ tools.biome: enforced by lint:biome" in out
    assert not (repo.parent / "proj.memory").exists()


# --- a hook counts only when git runs it ------------------------------------

RUFF_CONFIG = '[project]\nname = "x"\n\n[tool.ruff]\nline-length = 100\n'
RUFF_HOOK = "#!/bin/sh\nuv run ruff check .\n"
PRE_COMMIT_SHIM = (
    "#!/usr/bin/env bash\n# File generated by pre-commit: https://pre-commit.com\n"
    "ARGS=(hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit)\n"
    'exec pre-commit "${ARGS[@]}"\n'
)
NOT_RUN = "found in .githooks/pre-push, but core.hooksPath is not set, so git does not run it"


def test_shared_hook_without_hooks_path_is_advisory(repo, capsys, tools_preset):
    write(repo, "pyproject.toml", RUFF_CONFIG)
    hook(repo, ".githooks/pre-push", RUFF_HOOK)
    found = detection.detect(repo)["ruff-run"]
    assert not found.found
    assert found.reason == NOT_RUN
    code, out = run(capsys, "preset", "show", "tools", "--detect")
    assert code == 0
    assert f"+ tools.ruff: advisory (ruff config in pyproject.toml; {NOT_RUN})" in out
    assert main(["init", "--preset", "tools"]) == 0
    assert "enforced_by" not in rules_by_key(repo)["tools.ruff"]


def test_shared_hook_with_hooks_path_is_enforced(repo):
    write(repo, "pyproject.toml", RUFF_CONFIG)
    hook(repo, ".githooks/pre-push", RUFF_HOOK)
    git(repo, "config", "core.hooksPath", ".githooks")
    found = detection.detect(repo)["ruff-run"]
    assert found.found and found.reason == "run by .githooks/pre-push"


def test_local_hook_counts_only_when_executable_and_not_a_sample(repo):
    write(repo, "pyproject.toml", RUFF_CONFIG)
    hook(repo, ".git/hooks/pre-commit", RUFF_HOOK)
    assert detection.detect(repo)["ruff-run"].found
    (repo / ".git" / "hooks" / "pre-commit").chmod(0o644)
    found = detection.detect(repo)["ruff-run"]
    assert not found.found
    assert "found in .git/hooks/pre-commit, but it is not executable" in found.reason
    (repo / ".git" / "hooks" / "pre-commit").unlink()
    hook(repo, ".git/hooks/pre-commit.sample", RUFF_HOOK)
    assert not detection.detect(repo)["ruff-run"].found


def test_local_hook_found_from_a_worktree(repo):
    write(repo, "pyproject.toml", RUFF_CONFIG)
    git(repo, "add", "pyproject.toml")
    git(repo, "commit", "-q", "-m", "ruff")
    hook(repo, ".git/hooks/pre-commit", RUFF_HOOK)
    tree = add_worktree(repo, "feat-x")
    found = detection.detect(tree)["ruff-run"]
    assert found.found and "pre-commit" in found.reason


def test_pre_commit_config_counts_only_with_the_shim(repo):
    write(repo, "pyproject.toml", RUFF_CONFIG)
    write(
        repo, ".pre-commit-config.yaml", "repos:\n  - repo: local\n    hooks:\n      - id: ruff\n"
    )
    hook(repo, ".git/hooks/pre-commit", PRE_COMMIT_SHIM)
    found = detection.detect(repo)["ruff-run"]
    assert found.found and ".pre-commit-config.yaml" in found.reason
    (repo / ".git" / "hooks" / "pre-commit").unlink()
    found = detection.detect(repo)["ruff-run"]
    assert not found.found
    assert found.reason.startswith("found in .pre-commit-config.yaml, but ")


def test_lefthook_config_counts_only_with_the_shim(repo):
    write(repo, "pyproject.toml", RUFF_CONFIG)
    write(repo, "lefthook.yml", "pre-commit:\n  commands:\n    lint:\n      run: ruff check .\n")
    assert not detection.detect(repo)["ruff-run"].found
    hook(repo, ".git/hooks/pre-commit", '#!/bin/sh\nlefthook run "pre-commit" "$@"\n')
    assert detection.detect(repo)["ruff-run"].found


def test_ci_counts_whatever_the_hook_settings(repo):
    write(repo, "pyproject.toml", RUFF_CONFIG)
    write(
        repo, ".github/workflows/ci.yml", "jobs:\n  lint:\n    steps:\n      - run: ruff check .\n"
    )
    git(repo, "config", "core.hooksPath", "no-such-folder")
    found = detection.detect(repo)["ruff-run"]
    assert found.found and found.reason == "run by .github/workflows/ci.yml"


def test_plain_folder_counts_ci_but_not_hooks(tmp_path):
    root = tmp_path / "plain"
    write(root, "pyproject.toml", RUFF_CONFIG)
    hook(root, ".githooks/pre-push", RUFF_HOOK)
    hook(root, ".git/hooks/pre-commit", RUFF_HOOK)
    found = detection.detect(root)["ruff-run"]
    assert not found.found
    assert "not a git repo" in found.reason
    write(root, ".gitlab-ci.yml", "lint:\n  script: ruff check .\n")
    assert detection.detect(root)["ruff-run"].found
