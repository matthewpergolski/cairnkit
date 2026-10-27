"""pre-push and post-merge run the gated auto-tidy step and never fail git."""

import io
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import git, make_fact, read_jsonl, write_facts

from cairnkit.cli import main

DAY0 = "2026-10-20T12:00:00+00:00"
DAY1 = "2026-10-21T12:00:00+00:00"
DAY2 = "2026-10-22T12:00:00+00:00"
DAY8 = "2026-10-28T12:00:00+00:00"
A, B, C = "f-20261001-0001", "f-20261002-0002", "f-20261003-0003"
D, E = "f-20261004-0004", "f-20261005-0005"


def install(capsys):
    capsys.readouterr()
    assert main(["hooks", "install", "--agent", "generic"]) == 0


def start(capsys, monkeypatch, when):
    monkeypatch.setenv("MEMORY_NOW", when)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    capsys.readouterr()
    assert main(["hook", "session-start", "--agent", "generic"]) == 0


def open_gate(capsys, monkeypatch):
    for when in (DAY0, DAY1, DAY2, DAY8):
        start(capsys, monkeypatch, when)


def status(fid):
    from cairnkit.memory import Memory
    from cairnkit.paths import find_project

    return Memory.open(find_project(), None).states[fid]["status"]


def state_bytes(mem):
    return (mem / ".auto-tidy-state.json").read_bytes()


def cases():
    return [
        make_fact(A, "Deploys need a clean tree.", learned_at="2026-10-01T00:00:00+00:00"),
        make_fact(B, "deploys need a CLEAN tree!", learned_at="2026-10-02T00:00:00+00:00"),
        make_fact(C, "Working note.", scope="short", expires_at="2026-10-10T00:00:00+00:00"),
    ]


def git_quiet(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    noisy = result.stdout + result.stderr
    assert result.returncode == 0, noisy
    assert "Traceback" not in noisy
    assert "auto-tidy" not in noisy
    assert "error:" not in noisy.lower()
    return result


def push_main(repo):
    bare = repo.parent / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        git(repo, "remote", "add", "origin", str(bare))
    name = f"push-{time.time_ns()}.txt"
    (repo / name).write_text("x\n")
    git(repo, "add", name)
    git_quiet(repo, "commit", "-q", "-m", "push marker")
    git_quiet(repo, "push", "-q", "origin", "HEAD:main")


def merge_side(repo):
    name = f"side-{time.time_ns()}"
    git(repo, "checkout", "-q", "-b", name)
    (repo / f"{name}.txt").write_text("y\n")
    git(repo, "add", f"{name}.txt")
    git_quiet(repo, "commit", "-q", "-m", name)
    git(repo, "checkout", "-q", "main")
    git_quiet(repo, "merge", "-q", "--no-ff", "--no-edit", name)


def test_a_push_before_the_gate_reports_and_retires_nothing(repo, mem, capsys, monkeypatch):
    install(capsys)
    start(capsys, monkeypatch, DAY0)
    write_facts(mem, cases())
    before = state_bytes(mem)
    push_main(repo)
    assert status(A) == "active" and status(C) == "active"
    assert not (mem / "facts" / "auto-tidy.jsonl").exists()
    assert state_bytes(mem) == before
    log = (mem / "auto-tidy.log").read_text()
    assert "would retire" in log and A in log and C in log


def test_a_push_after_the_gate_retires_duplicates_and_ended_facts(repo, mem, capsys, monkeypatch):
    install(capsys)
    open_gate(capsys, monkeypatch)
    write_facts(mem, cases())
    before_facts = (mem / "facts" / "main.jsonl").read_bytes()
    before_state = state_bytes(mem)
    push_main(repo)
    assert status(A) == "superseded" and status(B) == "active" and status(C) == "expired"
    assert (mem / "facts" / "main.jsonl").read_bytes() == before_facts
    assert state_bytes(mem) == before_state
    records = read_jsonl(mem / "facts" / "auto-tidy.jsonl")
    assert {rec["id"] for rec in records} == {A, C}
    assert all(rec["writer"] == "auto-tidy" and rec["type"] == "change" for rec in records)
    log = (mem / "auto-tidy.log").read_text()
    assert f"memory change {A} --status active" in log
    assert f"memory change {C} --status active" in log and f"memory keep {C}" in log


def test_a_merge_after_the_gate_retires_too(repo, mem, capsys, monkeypatch):
    install(capsys)
    open_gate(capsys, monkeypatch)
    write_facts(
        mem,
        [
            make_fact(D, "Fonts load from the CDN.", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(E, "FONTS load from the CDN!", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    before = state_bytes(mem)
    merge_side(repo)
    assert status(D) == "superseded"
    assert state_bytes(mem) == before
    assert "memory change" in (mem / "auto-tidy.log").read_text()


def test_a_git_hook_retire_is_not_written_again_by_session_start(repo, mem, capsys, monkeypatch):
    install(capsys)
    open_gate(capsys, monkeypatch)
    write_facts(
        mem,
        [
            make_fact(A, "Deploys need a clean tree.", learned_at="2026-10-01T00:00:00+00:00"),
            make_fact(B, "deploys need a CLEAN tree!", learned_at="2026-10-02T00:00:00+00:00"),
        ],
    )
    hook = repo / ".git" / "hooks" / "pre-push"
    ran = subprocess.run([str(hook)], cwd=repo, capture_output=True, text=True)
    assert ran.returncode == 0 and ran.stdout == "" and ran.stderr == ""
    assert status(A) == "superseded"
    assert len(read_jsonl(mem / "facts" / "auto-tidy.jsonl")) == 1
    start(capsys, monkeypatch, DAY8)
    assert len(read_jsonl(mem / "facts" / "auto-tidy.jsonl")) == 1
    assert len((mem / "auto-tidy.log").read_text().splitlines()) == 1


def test_a_slow_tidy_step_returns_0_quickly(mem, monkeypatch, capsys):
    started = {"yes": False}
    finished = {"yes": False}

    def slow(*args, **kwargs):
        started["yes"] = True
        time.sleep(30)
        finished["yes"] = True

    monkeypatch.setattr("cairnkit.autotidy.decide", slow)
    capsys.readouterr()
    began = time.monotonic()
    assert main(["hook", "pre-push"]) == 0
    assert time.monotonic() - began < 8
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
    assert started["yes"] and not finished["yes"]


def test_git_events_exit_0_with_no_memory(repo, capsys):
    install(capsys)
    push_main(repo)
    merge_side(repo)


def test_git_events_exit_0_when_the_memory_folder_is_removed(repo, mem, capsys):
    install(capsys)
    mem.rename(mem.with_name("proj.memory.gone"))
    push_main(repo)
    merge_side(repo)


def test_git_events_exit_0_when_config_is_corrupt(repo, mem, capsys):
    install(capsys)
    (mem / "config.toml").write_text("not = [toml\n")
    push_main(repo)
    merge_side(repo)
    capsys.readouterr()
    assert main(["hook", "post-merge"]) == 0
    assert capsys.readouterr().out == ""


def test_git_events_exit_0_when_the_python_path_is_missing(repo, mem, capsys):
    install(capsys)
    folder = repo / ".git" / "hooks"
    for path in folder.iterdir():
        if path.is_file() and sys.executable in path.read_text():
            path.write_text(path.read_text().replace(sys.executable, "/no/such/cairnkit-python"))
    push_main(repo)
    merge_side(repo)


def test_a_hung_python_start_does_not_stall_the_push(repo, mem, capsys, tmp_path):
    """The shell block must bound process start, not only the in-process SIGALRM budget."""
    install(capsys)
    fake = tmp_path / "hung-python"
    fake.write_text("#!/bin/sh\nexec sleep 60\n")
    fake.chmod(0o755)
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(hook.read_text().replace(sys.executable, str(fake)))
    bare = repo.parent / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        git(repo, "remote", "add", "origin", str(bare))
    (repo / "hung-push.txt").write_text("x\n")
    git(repo, "add", "hung-push.txt")
    git_quiet(repo, "commit", "-q", "-m", "hung push marker")
    began = time.monotonic()
    result = subprocess.run(
        ["git", "push", "-q", "origin", "HEAD:main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - began
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "" and result.stderr == ""
    assert elapsed < 8, f"hung interpreter stalled the push for {elapsed:.1f}s"


def test_git_events_print_nothing_when_cairnkit_is_missing(repo, mem, capsys):
    """An existing interpreter without cairnkit must not print to the push terminal."""
    install(capsys)
    # A real system python that is not the test env (so cairnkit is not importable).
    py = "/usr/bin/python3"
    assert Path(py).is_file() and py != sys.executable
    probe = subprocess.run([py, "-c", "import cairnkit"], capture_output=True, text=True)
    assert probe.returncode != 0
    assert "No module named" in probe.stderr and "cairnkit" in probe.stderr
    # Only the quiet tidy hooks: pre-commit must keep a working interpreter.
    for name in ("pre-push", "post-merge"):
        path = repo / ".git" / "hooks" / name
        path.write_text(path.read_text().replace(sys.executable, py))
    bare = repo.parent / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        git(repo, "remote", "add", "origin", str(bare))
    (repo / "missing-mod.txt").write_text("x\n")
    git(repo, "add", "missing-mod.txt")
    git_quiet(repo, "commit", "-q", "-m", "missing module marker")
    result = subprocess.run(
        ["git", "push", "-q", "origin", "HEAD:main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""
    assert result.stderr == ""
    assert "No module named" not in result.stderr
    assert "cairnkit" not in result.stderr


def test_git_events_exit_0_when_the_store_is_locked(repo, mem, capsys):
    import fcntl

    install(capsys)
    lock = (mem / ".auto-tidy.lock").open("a")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    try:
        push_main(repo)
        merge_side(repo)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def test_pre_push_leaves_the_ref_list_for_a_later_hook(repo, mem, capsys):
    path = repo / ".git" / "hooks" / "pre-push"
    path.write_text('#!/bin/sh\ncat > "$PWD/seen-refs.txt"\n')
    path.chmod(0o755)
    install(capsys)
    push_main(repo)
    seen = (repo / "seen-refs.txt").read_text()
    assert "refs/heads/" in seen


def test_pre_push_no_verify_skips_the_hook(repo, mem, capsys):
    """git push --no-verify skips every pre-push hook, including ours."""
    install(capsys)
    hook = repo / ".git" / "hooks" / "pre-push"
    hook.write_text(hook.read_text() + 'echo RAN > "$PWD/hook-ran.txt"\n')
    bare = repo.parent / "remote.git"
    if not bare.exists():
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        git(repo, "remote", "add", "origin", str(bare))
    (repo / "no-verify.txt").write_text("x\n")
    git(repo, "add", "no-verify.txt")
    git_quiet(repo, "commit", "-q", "-m", "no-verify marker")
    git_quiet(repo, "push", "-q", "--no-verify", "origin", "HEAD:main")
    assert not (repo / "hook-ran.txt").exists()
    (repo / "verify.txt").write_text("y\n")
    git(repo, "add", "verify.txt")
    git_quiet(repo, "commit", "-q", "-m", "verify marker")
    git_quiet(repo, "push", "-q", "origin", "HEAD:main")
    assert (repo / "hook-ran.txt").read_text() == "RAN\n"


def test_hooks_exit_0_and_print_nothing_outside_git(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for event in ("pre-push", "post-merge"):
        capsys.readouterr()
        assert main(["hook", event]) == 0
        out = capsys.readouterr()
        assert out.out == "" and out.err == ""


@pytest.mark.parametrize("event", ["pre-push", "post-merge"])
def test_a_git_event_does_not_count_as_a_session_start(repo, mem, capsys, monkeypatch, event):
    start(capsys, monkeypatch, DAY0)
    before = state_bytes(mem)
    capsys.readouterr()
    assert main(["hook", event]) == 0
    assert capsys.readouterr().out == ""
    assert state_bytes(mem) == before
