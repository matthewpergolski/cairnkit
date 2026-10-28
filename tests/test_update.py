"""`memory update`: find the source, check, fetch, build, install, verify.

No test uses the network or the real uv. The source is a throwaway git repo,
and a fake `uv` on PATH logs its arguments and writes a fake `memory`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from conftest import git

from cairnkit import install_source
from cairnkit.cli import main

FAKE_UV = """\
#!/bin/sh
echo "$@" >> "$FAKE_UV_LOG"
case "$1" in
  build)
    echo "begin build" >> "$FAKE_UV_LOG.order"
    if [ -n "$FAKE_UV_SLEEP" ]; then sleep "$FAKE_UV_SLEEP"; fi
    if [ -n "$FAKE_UV_BUILD_FAIL" ]; then echo "build broke here" >&2; exit 1; fi
    for a; do last="$a"; done
    (cd "$last" && find . -type f | sed 's|^\\./||' | sort) > "$FAKE_UV_LOG.built"
    while [ $# -gt 0 ]; do
      if [ "$1" = "--out-dir" ]; then
        mkdir -p "$2"; ls -A "$last" > "$2/cairnkit-x-py3-none-any.whl"
      fi
      shift
    done ;;
  tool)
    if [ -n "$FAKE_UV_INSTALL_FAIL" ]; then echo "install broke here" >&2; exit 1; fi
    printf '#!/bin/sh\\necho "memory %s"\\n' "$FAKE_NEW_VERSION" > "$FAKE_BIN/memory"
    echo "end install" >> "$FAKE_UV_LOG.order"
    chmod +x "$FAKE_BIN/memory" ;;
esac
"""


def make_source(path: Path, version: str = "0.2.0") -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.invalid")
    (path / "pyproject.toml").write_text(f'[project]\nname = "cairnkit"\nversion = "{version}"\n')
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "source")
    return path


def head(path: Path) -> str:
    return git(path, "rev-parse", "HEAD").strip()


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A fake uv tool env with a receipt, a fake uv on PATH, and a source folder."""
    source = make_source(tmp_path / "src")
    env = tmp_path / "tools" / "cairnkit"
    env.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(FAKE_UV)
    (bin_dir / "uv").chmod(0o755)
    (env / "uv-receipt.toml").write_text(
        "[tool]\n"
        f'requirements = [{{ name = "cairnkit", directory = "{source}" }}]\n'
        "entrypoints = [\n"
        f'    {{ name = "memory", install-path = "{bin_dir / "memory"}", '
        'from = "cairnkit" },\n]\n'
    )
    log = tmp_path / "uv.log"
    monkeypatch.setenv("FAKE_UV_LOG", str(log))
    monkeypatch.setenv("FAKE_BIN", str(bin_dir))
    monkeypatch.setenv("FAKE_NEW_VERSION", "0.2.0")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(install_source, "tool_env", lambda: env)
    monkeypatch.setattr(install_source, "current_version", lambda: "0.1.0")

    class Machine:
        pass

    m = Machine()
    m.source, m.env, m.bin, m.log = source, env, bin_dir, log
    m.uv_calls = lambda: log.read_text().splitlines() if log.exists() else []
    m.record = lambda: json.loads((env / install_source.RECORD).read_text())
    return m


def test_update_from_a_local_folder_shows_each_step_and_both_versions(machine, capsys):
    assert main(["update"]) == 0
    out = capsys.readouterr().out
    assert f"Source: {machine.source} (folder)" in out
    for step in ("Check", "Fetch", "Build", "Install", "Verify"):
        assert f"  {step}... done" in out
    assert "0.1.0 -> 0.2.0" in out
    calls = machine.uv_calls()
    build = next(c for c in calls if c.startswith("build --wheel --out-dir "))
    assert not build.endswith(str(machine.source))  # a fixed copy, not the live folder
    assert install_line(machine).startswith("tool install --force --reinstall cairnkit @ file:")
    assert install_line(machine).endswith(".whl")
    record = machine.record()
    assert record["source"] == str(machine.source)
    assert record["commit"] == head(machine.source)
    assert record["version"] == "0.2.0"


def install_line(machine) -> str:
    return next(c for c in machine.uv_calls() if c.startswith("tool install"))


def test_update_installs_exactly_the_checked_commit(machine, monkeypatch, capsys):
    checked = head(machine.source)
    real_latest = install_source.latest

    def latest_then_commit(source, timeout=3.0):
        found = real_latest(source, timeout)
        (machine.source / "late.txt").write_text("came after the check\n")
        git(machine.source, "add", "-A")
        git(machine.source, "commit", "-qm", "late")
        return found

    monkeypatch.setattr(install_source, "latest", latest_then_commit)
    assert main(["update"]) == 0
    built = (machine.log.parent / "uv.log.built").read_text().split()
    assert "pyproject.toml" in built and "late.txt" not in built
    assert machine.record()["commit"] == checked


def test_a_wheel_receipt_falls_back_to_the_record(machine):
    record = {"source": str(machine.source), "commit": head(machine.source), "version": "0.1.0"}
    (machine.env / install_source.RECORD).write_text(json.dumps(record))
    (machine.env / "uv-receipt.toml").write_text(
        '[tool]\nrequirements = [{ name = "cairnkit", path = "/gone/cairnkit.whl" }]\n'
    )
    source, commit = install_source.installed(None)
    assert source == install_source.parse(str(machine.source))
    assert commit == head(machine.source)


def test_an_install_under_the_old_name_updates_to_cairnkit(machine, monkeypatch, capsys):
    """An install from before the rename: its uv tool env and receipt say project-memory."""
    legacy = machine.env.parent / "project-memory"
    legacy.mkdir()
    receipt = (machine.env / "uv-receipt.toml").read_text()
    (legacy / "uv-receipt.toml").write_text(receipt.replace('"cairnkit"', '"project-memory"'))
    (machine.env / "uv-receipt.toml").unlink()
    record = {"source": str(machine.source), "commit": "0" * 40, "version": "0.1.0"}
    (legacy / "project-memory-install.json").write_text(json.dumps(record))
    monkeypatch.setattr(install_source, "tool_env", lambda: legacy)
    assert install_source.installed(None) == (install_source.parse(str(machine.source)), "0" * 40)
    assert main(["update"]) == 0
    out = capsys.readouterr().out
    assert install_line(machine).startswith("tool install --force --reinstall cairnkit @ file:")
    assert machine.record()["commit"] == head(machine.source)  # in the new cairnkit env
    assert "uv tool uninstall project-memory" in out
    # Old hooks call the old environment: refresh each repo before the old tool goes.
    assert "still run it" in out
    assert out.index("memory init --refresh") < out.index("uv tool uninstall project-memory")


def test_update_twice_changes_nothing_the_second_time(machine, monkeypatch, capsys):
    assert main(["update"]) == 0
    monkeypatch.setattr(install_source, "current_version", lambda: "0.2.0")  # the new process
    capsys.readouterr()
    calls = len(machine.uv_calls())
    assert main(["update"]) == 0
    out = capsys.readouterr().out
    assert "Already up to date (0.2.0)." in out
    assert len(machine.uv_calls()) == calls


def test_a_new_commit_with_the_same_version_is_an_update(machine, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_NEW_VERSION", "0.1.0")
    (machine.source / "pyproject.toml").write_text(
        '[project]\nname = "cairnkit"\nversion = "0.1.0"\n'
    )
    git(machine.source, "commit", "-qam", "same version")
    assert main(["update"]) == 0
    first = head(machine.source)
    (machine.source / "new.txt").write_text("x\n")
    git(machine.source, "add", "-A")
    git(machine.source, "commit", "-qm", "newer")
    capsys.readouterr()
    assert main(["update", "--check"]) == 0
    out = capsys.readouterr().out
    assert "Update available" in out
    assert first[:7] in out and head(machine.source)[:7] in out


def test_update_check_shows_commit_subjects_between_refs(machine, monkeypatch, capsys):
    """When a local folder moved on, --check lists the subjects that would land."""
    assert main(["update"]) == 0
    monkeypatch.setattr(install_source, "current_version", lambda: "0.2.0")
    git(machine.source, "commit", "-q", "--allow-empty", "-m", "Add the quiet hook.")
    git(machine.source, "commit", "-q", "--allow-empty", "-m", "Hide the alarm line.")
    capsys.readouterr()
    assert main(["update", "--check"]) == 0
    out = capsys.readouterr().out
    assert "Update available" in out
    assert "Add the quiet hook." in out
    assert "Hide the alarm line." in out


def test_update_prints_commit_subjects_after_a_successful_install(machine, monkeypatch, capsys):
    assert main(["update"]) == 0
    monkeypatch.setattr(install_source, "current_version", lambda: "0.2.0")
    git(machine.source, "commit", "-q", "--allow-empty", "-m", "Record the installed ref.")
    capsys.readouterr()
    assert main(["update"]) == 0
    out = capsys.readouterr().out
    assert "Record the installed ref." in out
    assert "memory updated:" in out


def test_update_check_shows_a_github_compare_url(machine, monkeypatch, capsys):
    """A GitHub git URL has no local history; --check prints a compare link instead."""
    url = "https://github.com/example/cairnkit"
    old = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    new = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    (machine.env / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "cairnkit", git = "{url}" }}]\n'
        f'entrypoints = [{{ name = "memory", install-path = "{machine.bin / "memory"}" }}]\n'
    )
    record = {"source": f"git+{url}", "commit": old, "version": "0.1.0"}
    (machine.env / install_source.RECORD).write_text(json.dumps(record))
    monkeypatch.setattr(
        install_source, "latest", lambda source, timeout=3.0: install_source.Latest(new, None)
    )
    assert main(["update", "--check"]) == 0
    out = capsys.readouterr().out
    assert "Update available" in out
    assert f"https://github.com/example/cairnkit/compare/{old[:7]}...{new[:7]}" in out


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (
            "https://github.com/example/cairnkit",
            "https://github.com/example/cairnkit/compare/aaa1111...bbb2222",
        ),
        (
            "https://github.com/example/cairnkit.git",
            "https://github.com/example/cairnkit/compare/aaa1111...bbb2222",
        ),
        (
            "git@github.com:example/cairnkit.git",
            "https://github.com/example/cairnkit/compare/aaa1111...bbb2222",
        ),
        ("https://gitlab.com/example/cairnkit", None),
        ("/tmp/local-folder", None),
    ],
)
def test_github_compare_url(spec, expected):
    assert install_source.github_compare_url(spec, "aaa1111ffff", "bbb2222eeee") == expected


def test_check_says_so_and_changes_nothing(machine, capsys):
    assert main(["update", "--check"]) == 0
    out = capsys.readouterr().out
    assert "Update available: 0.1.0 -> 0.2.0" in out
    assert "Run `memory update`" in out
    assert machine.uv_calls() == []
    assert not (machine.env / install_source.RECORD).exists()


def test_dry_run_lists_the_steps_and_changes_nothing(machine, capsys):
    assert main(["update", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Dry run: nothing will change." in out
    assert "would build: uv build --wheel" in out
    assert "would install: uv tool install --force --reinstall the built wheel" in out
    assert machine.uv_calls() == []
    assert not (machine.env / install_source.RECORD).exists()
    assert not install_source._cache_path().exists()  # no persistent state at all


def test_a_failed_build_stops_before_install_and_says_how_to_fix(machine, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_UV_BUILD_FAIL", "1")
    assert main(["update"]) == 1
    captured = capsys.readouterr()
    assert "  Build... failed" in captured.out
    assert "error: The source did not build." in captured.err
    assert "build broke here" in captured.err
    assert "Fix:" in captured.err
    assert not any(c.startswith("tool install") for c in machine.uv_calls())


def test_a_new_tool_that_reports_the_wrong_version_fails_verify(machine, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_NEW_VERSION", "0.0.9")
    assert main(["update"]) == 1
    captured = capsys.readouterr()
    assert "  Verify... failed" in captured.out
    assert "0.0.9" in captured.err and "Fix:" in captured.err
    assert not (machine.env / install_source.RECORD).exists()


def test_no_known_source_says_how_to_give_one(machine, capsys):
    (machine.env / "uv-receipt.toml").unlink()
    assert main(["update"]) == 1
    err = capsys.readouterr().err
    assert "error: " in err
    assert "memory update --source" in err


def test_source_flag_wins_over_the_receipt(machine, tmp_path, capsys):
    other = make_source(tmp_path / "other")
    assert main(["update", "--source", str(other)]) == 0
    assert f"Source: {other} (folder)" in capsys.readouterr().out
    assert install_line(machine).endswith(".whl")
    assert machine.record()["source"] == str(other)


def test_a_folder_with_uncommitted_changes_is_refused(machine, capsys):
    (machine.source / "pyproject.toml").write_text("changed\n")
    assert main(["update"]) == 1
    err = capsys.readouterr().err
    assert "uncommitted changes" in err
    assert "Fix:" in err
    assert machine.uv_calls() == []


def test_a_git_url_source_is_fetched_built_and_installed(machine, capsys):
    url = machine.source.as_uri()  # file:// works offline, like a remote
    assert main(["update", "--source", f"git+{url}"]) == 0
    out = capsys.readouterr().out
    assert f"Source: {url} (git)" in out
    assert "  Fetch... done" in out
    assert install_line(machine).endswith(".whl")
    assert machine.record()["commit"] == head(machine.source)


def test_an_editable_install_needs_no_update(machine, capsys):
    (machine.env / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "cairnkit", editable = "{machine.source}" }}]\n'
    )
    assert main(["update"]) == 0
    assert "editable" in capsys.readouterr().out
    assert machine.uv_calls() == []


def test_a_folder_moved_back_to_an_older_commit_is_not_newer(machine):
    first = head(machine.source)
    (machine.source / "a.txt").write_text("a\n")
    git(machine.source, "add", "-A")
    git(machine.source, "commit", "-qm", "later")
    later = head(machine.source)
    source = install_source.parse(str(machine.source))
    assert install_source.is_newer(source, "0.2.0", first, install_source.Latest(later, "0.2.0"))
    assert not install_source.is_newer(
        source, "0.2.0", later, install_source.Latest(first, "0.2.0")
    )


def test_check_needs_no_uv_but_update_does(machine, monkeypatch, capsys):
    monkeypatch.setattr("cairnkit.update.shutil.which", lambda name: None)
    assert main(["update", "--check"]) == 0
    assert "Update available" in capsys.readouterr().out
    assert main(["update"]) == 1
    err = capsys.readouterr().err
    assert "uv is not on PATH." in err and "Fix: Install uv" in err


def test_a_folder_without_git_is_a_no_op_the_second_time(machine, tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    (plain / "src" / "pkg").mkdir(parents=True)
    (plain / "pyproject.toml").write_text('[project]\nname = "cairnkit"\nversion = "0.2.0"\n')
    (plain / "src" / "pkg" / "a.py").write_text("x = 1\n")
    (machine.env / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "cairnkit", directory = "{plain}" }}]\n'
        f'entrypoints = [{{ name = "memory", install-path = "{machine.bin / "memory"}" }}]\n'
    )
    assert main(["update"]) == 0
    assert machine.record()["commit"]  # a content hash stands in for the commit
    monkeypatch.setattr(install_source, "current_version", lambda: "0.2.0")  # the new process
    calls = len(machine.uv_calls())
    capsys.readouterr()
    assert main(["update"]) == 0
    assert "Already up to date (0.2.0)." in capsys.readouterr().out
    assert len(machine.uv_calls()) == calls
    (plain / "src" / "pkg" / "__pycache__").mkdir()
    (plain / "src" / "pkg" / "__pycache__" / "a.pyc").write_bytes(b"cache")
    assert main(["update", "--check"]) == 0
    assert "Up to date" in capsys.readouterr().out  # caches do not count
    (plain / "src" / "pkg" / "a.py").write_text("x = 2\n")
    assert main(["update", "--check"]) == 0
    assert "Update available" in capsys.readouterr().out


def advance_after_check(machine, monkeypatch, rewrite: bool = False):
    """Let the check read the remote, then move the remote on before the fetch."""
    real_latest = install_source.latest

    def latest_then_move(source, timeout=3.0):
        found = real_latest(source, timeout)
        (machine.source / "late.txt").write_text("came after the check\n")
        git(machine.source, "add", "-A")
        if rewrite:  # the checked commit is no longer on any branch
            git(machine.source, "commit", "-q", "--amend", "-m", "rewritten")
            git(machine.source, "reflog", "expire", "--expire=now", "--all")
            git(machine.source, "gc", "-q", "--prune=now")
        else:
            git(machine.source, "commit", "-qm", "late")
        return found

    monkeypatch.setattr(install_source, "latest", latest_then_move)


def test_a_git_source_that_moves_after_the_check_installs_the_checked_commit(
    machine, monkeypatch, capsys
):
    checked = head(machine.source)
    advance_after_check(machine, monkeypatch)
    assert main(["update", "--source", f"git+{machine.source.as_uri()}"]) == 0
    built = (machine.log.parent / "uv.log.built").read_text().split()
    assert "pyproject.toml" in built and "late.txt" not in built
    assert machine.record()["commit"] == checked


def test_a_git_source_that_drops_the_checked_commit_fails_clearly(machine, monkeypatch, capsys):
    advance_after_check(machine, monkeypatch, rewrite=True)
    assert main(["update", "--source", f"git+{machine.source.as_uri()}"]) == 1
    captured = capsys.readouterr()
    assert "  Fetch... failed" in captured.out
    # git says "not our ref" for a commit it no longer has, so this takes the bounded fetch.
    assert "could not be fetched" in captured.err
    assert "Fix: Run `memory update` again" in captured.err
    assert not any(c.startswith(("build", "tool install")) for c in machine.uv_calls())
    assert not (machine.env / install_source.RECORD).exists()


def wheel_of(line: str) -> Path:
    from urllib.parse import unquote, urlparse

    return Path(unquote(urlparse(line.split(" @ ", 1)[1]).path))


def kept_wheels() -> list[Path]:
    from cairnkit.skills import cache_dir

    return sorted((cache_dir() / "wheels").rglob("*.whl"))


def test_a_failed_install_keeps_the_wheel_of_the_current_install(machine, monkeypatch, capsys):
    assert main(["update"]) == 0
    first = wheel_of(install_line(machine))
    before = first.read_bytes()
    (machine.source / "late.txt").write_text("a newer commit, the same version\n")
    git(machine.source, "add", "-A")
    git(machine.source, "commit", "-qm", "newer")
    monkeypatch.setattr(install_source, "current_version", lambda: "0.2.0")  # the new process
    monkeypatch.setenv("FAKE_UV_INSTALL_FAIL", "1")
    assert main(["update"]) == 1
    assert "install broke here" in capsys.readouterr().err
    assert first.read_bytes() == before  # the receipt's wheel is intact
    assert kept_wheels() == [first]  # the failed candidate is gone
    monkeypatch.delenv("FAKE_UV_INSTALL_FAIL")
    assert main(["update"]) == 0
    second = wheel_of([c for c in machine.uv_calls() if c.startswith("tool install")][-1])
    assert second != first
    assert kept_wheels() == [second]


def test_a_folder_without_git_keeps_inner_links_and_skips_logs(
    machine, tmp_path, monkeypatch, capsys
):
    plain = tmp_path / "plain"
    (plain / "src" / "pkg").mkdir(parents=True)
    (plain / "shared").mkdir()
    (plain / "pyproject.toml").write_text('[project]\nname = "cairnkit"\nversion = "0.2.0"\n')
    (plain / "shared" / "real.py").write_text("x = 1\n")
    (plain / "src" / "pkg" / "mod.py").symlink_to("../../shared/real.py")
    (plain / "src" / "pkg" / "linked").symlink_to("../../shared", target_is_directory=True)
    (plain / "src" / "loop").symlink_to("..", target_is_directory=True)  # must not hang
    (tmp_path / "outside.py").write_text("not part of the source\n")
    (plain / "src" / "pkg" / "out.py").symlink_to(tmp_path / "outside.py")
    (machine.env / "uv-receipt.toml").write_text(
        f'[tool]\nrequirements = [{{ name = "cairnkit", directory = "{plain}" }}]\n'
        f'entrypoints = [{{ name = "memory", install-path = "{machine.bin / "memory"}" }}]\n'
    )
    assert main(["update"]) == 0
    built = set((machine.log.parent / "uv.log.built").read_text().split())
    assert {"src/pkg/mod.py", "src/pkg/linked/real.py", "shared/real.py"} <= built
    assert "src/pkg/out.py" not in built
    monkeypatch.setattr(install_source, "current_version", lambda: "0.2.0")  # the new process
    for junk in ("debug.log", "src/pkg/a.pyc", "htmlcov/index.html", "src/pkg/a.py.swp"):
        (plain / junk).parent.mkdir(parents=True, exist_ok=True)
        (plain / junk).write_text("noise\n")
    calls = len(machine.uv_calls())
    capsys.readouterr()
    assert main(["update"]) == 0
    assert "Already up to date (0.2.0)." in capsys.readouterr().out
    assert len(machine.uv_calls()) == calls


def test_cleanup_keeps_the_wheel_that_the_receipt_points_to(machine, capsys):
    from cairnkit import update

    # Another update finished in between: the receipt now names its wheel.
    other = update.wheels_dir() / "install-other" / "cairnkit-0.2.0-py3-none-any.whl"
    other.parent.mkdir(parents=True)
    other.write_text("the other try's wheel\n")
    (machine.env / "uv-receipt.toml").write_text(
        "[tool]\n"
        f'requirements = [{{ name = "cairnkit", url = "{other.as_uri()}" }}]\n'
        f'entrypoints = [{{ name = "memory", install-path = "{machine.bin / "memory"}" }}]\n'
    )
    assert main(["update", "--source", str(machine.source)]) == 0
    assert other.read_text() == "the other try's wheel\n"


def test_each_tool_environment_has_its_own_wheels(machine, tmp_path, monkeypatch):
    from cairnkit import update

    first = update.wheels_dir()
    monkeypatch.setattr(install_source, "tool_env", lambda: tmp_path / "other-env")
    assert update.wheels_dir() != first


def record_runs(
    monkeypatch, refuse_by_id: bool = False, fail_with: str | None = None
) -> list[list[str]]:
    """Record the commands memory update runs. Optionally fail a fetch by commit id."""
    from cairnkit import update

    runs: list[list[str]] = []
    real_run = update._run

    def run(argv, timeout=900):
        runs.append(argv)
        by_id = "fetch" in argv and argv[-1] != "+refs/heads/*:refs/remotes/origin/*"
        if refuse_by_id and by_id:
            return 1, "error: Server does not allow request for unadvertised object"
        if fail_with and by_id:
            return 128, fail_with
        return real_run(argv, timeout)

    monkeypatch.setattr(update, "_run", run)
    return runs


def test_a_git_source_fetches_only_the_checked_commit(machine, monkeypatch, capsys):
    checked = head(machine.source)
    runs = record_runs(monkeypatch)
    assert main(["update", "--source", f"git+{machine.source.as_uri()}"]) == 0
    fetches = [argv for argv in runs if "fetch" in argv]
    assert fetches and fetches[0][-3:] == ["1", machine.source.as_uri(), checked]
    assert not any("clone" in argv for argv in runs)
    assert machine.record()["commit"] == checked


def test_a_server_that_refuses_a_fetch_by_id_falls_back(machine, monkeypatch, capsys):
    checked = head(machine.source)
    advance_after_check(machine, monkeypatch)
    runs = record_runs(monkeypatch, refuse_by_id=True)
    assert main(["update", "--source", f"git+{machine.source.as_uri()}"]) == 0
    fetches = [argv for argv in runs if "fetch" in argv]
    assert len(fetches) == 2
    assert "--depth" in fetches[1]  # the fallback is bounded too
    built = (machine.log.parent / "uv.log.built").read_text().split()
    assert "late.txt" not in built
    assert machine.record()["commit"] == checked


def hold_lock(path: Path):
    """A real second process that holds the update lock until it is killed."""
    import subprocess
    import sys

    path.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "import fcntl, sys, time\n"
        "f = open(sys.argv[1], 'a')\n"
        "fcntl.flock(f, fcntl.LOCK_EX)\n"
        "print('locked', flush=True)\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout.readline().strip() == "locked"
    return proc


def test_an_update_waits_for_the_lock_and_never_touches_the_other_try(machine, monkeypatch, capsys):
    from cairnkit import update

    other = update.wheels_dir() / "install-other" / "cairnkit-0.2.0-py3-none-any.whl"
    other.parent.mkdir(parents=True)
    other.write_text("the other update's wheel, still in use\n")
    monkeypatch.setattr(update, "LOCK_WAIT", 0.5)
    proc = hold_lock(update.lock_path())
    try:
        assert main(["update"]) == 1
    finally:
        proc.kill()
        proc.wait()
    captured = capsys.readouterr()
    assert "Another memory update is running. Waiting for it." in captured.out
    assert "error: Another memory update still runs." in captured.err
    assert "Fix:" in captured.err
    assert other.read_text() == "the other update's wheel, still in use\n"
    assert not any(c.startswith(("build", "tool install")) for c in machine.uv_calls())


def test_two_overlapping_updates_run_one_after_the_other(machine, monkeypatch, capsys):
    import threading

    monkeypatch.setenv("FAKE_UV_SLEEP", "0.4")
    codes = []
    threads = [threading.Thread(target=lambda: codes.append(main(["update"]))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert codes == [0, 0]
    order = (machine.log.parent / "uv.log.order").read_text().splitlines()
    assert order == ["begin build", "end install", "begin build", "end install"]
    assert len(kept_wheels()) == 1


def test_an_auth_or_network_failure_does_not_fall_back(machine, monkeypatch, capsys):
    message = "fatal: Authentication failed for 'https://example.invalid/m.git/'"
    runs = record_runs(monkeypatch, fail_with=message)
    assert main(["update", "--source", f"git+{machine.source.as_uri()}"]) == 1
    assert len([argv for argv in runs if "fetch" in argv]) == 1
    err = capsys.readouterr().err
    assert "Authentication failed" in err and "Fix: Check the network and the URL" in err
    assert not any(c.startswith(("build", "tool install")) for c in machine.uv_calls())


@pytest.mark.parametrize(
    ("output", "refused"),
    [
        ("fatal: remote error: upload-pack: not our ref 1234abcd", True),
        ("error: Server does not allow request for unadvertised object 1234abcd", True),
        ("fatal: couldn't find remote ref 1234abcd", True),
        ("fatal: Authentication failed for 'https://example.invalid/m.git/'", False),
        ("fatal: unable to access 'https://example.invalid/': Could not resolve host", False),
        ("fatal: repository 'https://example.invalid/m.git/' not found", False),
    ],
)
def test_only_a_refused_commit_id_counts_as_refused(output, refused):
    from cairnkit import update

    assert update.refuses_commit_id(output) is refused


def test_the_lock_holder_checks_the_remote_after_it_gets_the_lock(machine, monkeypatch, capsys):
    import threading
    import time

    from cairnkit import update

    proc = hold_lock(update.lock_path())  # another update runs
    codes = []
    waiting = threading.Thread(
        target=lambda: codes.append(main(["update", "--source", f"git+{machine.source.as_uri()}"]))
    )
    try:
        waiting.start()
        time.sleep(0.6)  # the waiting update has started
        (machine.source / "newest.txt").write_text("pushed while the other update ran\n")
        git(machine.source, "add", "-A")
        git(machine.source, "commit", "-qm", "newest")
        newest = head(machine.source)
    finally:
        proc.kill()
        proc.wait()
    waiting.join()
    assert codes == [0]
    assert machine.record()["commit"] == newest
    assert "newest.txt" in (machine.log.parent / "uv.log.built").read_text().split()


def test_update_imports_and_runs_without_fcntl(monkeypatch, tmp_path):
    """Windows has no fcntl. The module must import, and the lock must not fail."""
    import importlib.util
    import io
    import sys

    from cairnkit import update
    from cairnkit.progress import Progress

    monkeypatch.setitem(sys.modules, "fcntl", None)  # import fcntl now raises ImportError
    spec = importlib.util.spec_from_file_location("update_without_fcntl", update.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.fcntl is None
    monkeypatch.setattr(module, "lock_path", lambda: tmp_path / "update.lock")
    with module._locked(Progress(io.StringIO())):
        pass


def record_git_calls(monkeypatch) -> list[dict]:
    import subprocess

    calls: list[dict] = []
    real_run = subprocess.run

    def run(argv, *args, **kwargs):
        if argv and Path(str(argv[0])).name == "git":
            calls.append({"argv": argv, **kwargs})
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_git_never_prompts_and_never_waits_long(machine, monkeypatch, capsys):
    import subprocess

    calls = record_git_calls(monkeypatch)
    assert main(["update", "--source", f"git+{machine.source.as_uri()}"]) == 0
    commands = {call["argv"][1] if call["argv"][1] != "-C" else call["argv"][3] for call in calls}
    assert {"ls-remote", "init", "fetch", "checkout", "rev-parse"} <= commands
    for call in calls:
        assert call.get("stdin") is subprocess.DEVNULL, call["argv"]
        assert call.get("env", {}).get("GIT_TERMINAL_PROMPT") == "0", call["argv"]
        assert call.get("timeout") and call["timeout"] <= 300, call["argv"]


def test_git_messages_are_in_english_for_the_refusal_check(machine, monkeypatch, capsys):
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    calls = record_git_calls(monkeypatch)
    assert main(["update", "--source", f"git+{machine.source.as_uri()}"]) == 0
    assert calls
    for call in calls:
        assert call["env"]["LC_ALL"] == "C", call["argv"]


def test_a_commit_deeper_than_the_fallback_says_so(machine, monkeypatch, capsys):
    from cairnkit import update

    real_latest = install_source.latest

    def latest_then_many(source, timeout=3.0):
        found = real_latest(source, timeout)
        for n in range(update.FALLBACK_DEPTH + 1):  # the checked commit is now too deep
            git(machine.source, "commit", "-q", "--allow-empty", "-m", f"later {n}")
        return found

    monkeypatch.setattr(install_source, "latest", latest_then_many)
    record_runs(monkeypatch, refuse_by_id=True)
    assert main(["update", "--source", f"git+{machine.source.as_uri()}"]) == 1
    err = capsys.readouterr().err
    assert f"is not in the last {update.FALLBACK_DEPTH} commits of any branch" in err
    assert "Fix: Run `memory update` again. It checks the remote again" in err
    assert not any(c.startswith(("build", "tool install")) for c in machine.uv_calls())
