"""Put a pipe at each file that one command opens in the project or the memory folder, one at a
time, and run the command again. Report each run that hangs or ends in a Traceback.

    python odd_file_sweep.py PLAN.json RESULT.json

PLAN holds root, memdir, args, stdin and timeout. A first run records each file that the command
opens, with an audit hook, so a new read or write is in the sweep with no list to keep. A file in
`.git/` that git itself reads is skipped: only the hooks there are the tool's own.
Each run is a fork of this process, so cairnkit is imported once.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path


def _offline() -> None:
    """As the conftest: no network, no real install, no commands of other tools."""
    from cairnkit import install_source, skills

    def offline(*args, **kwargs):
        raise OSError("tests do not use the network")

    install_source._direct_url = lambda: None
    skills.fetch_text = offline
    skills.checkout = offline
    skills._which = lambda name: None
    skills._run = lambda argv, timeout=120: (1, "tests run no commands")


def _child(plan: dict, out: Path, record: Path | None) -> None:
    """Run the command in this forked process, then exit. Never returns."""
    code = 70
    try:
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        stdin = out.with_suffix(".stdin")
        stdin.write_text(plan["stdin"] or "", encoding="utf-8")
        os.dup2(os.open(stdin, os.O_RDONLY), 0)
        # These stay open until the fork exits.
        sys.stdin = open(0, encoding="utf-8", closefd=False)  # noqa: SIM115
        sys.stdout = open(1, "w", encoding="utf-8", closefd=False, buffering=1)  # noqa: SIM115
        sys.stderr = open(2, "w", encoding="utf-8", closefd=False, buffering=1)  # noqa: SIM115
        os.chdir(plan["root"])
        seen: set[str] = set()
        if record is not None:
            roots = tuple(os.path.realpath(plan[key]) + os.sep for key in ("root", "memdir"))

            def hook(event: str, args: tuple) -> None:
                if event != "open" or not isinstance(args[0], (str, bytes, os.PathLike)):
                    return
                path = os.path.realpath(os.fsdecode(args[0]))
                if path.startswith(roots):
                    seen.add(path)

            sys.addaudithook(hook)
        from cairnkit.cli import main

        try:
            code = main(plan["args"]) or 0
        finally:
            if record is not None:
                record.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except BaseException:
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
    os._exit(code)


def _run(plan: dict, work: Path, record: Path | None = None) -> tuple[bool, str]:
    """(hung, output) of one run in a fork."""
    out = work / "out.txt"
    pid = os.fork()
    if pid == 0:
        _child(plan, out, record)
    end = time.monotonic() + plan["timeout"]
    while time.monotonic() < end:
        done, _status = os.waitpid(pid, os.WNOHANG)
        if done:
            return False, out.read_text(encoding="utf-8", errors="replace")
        time.sleep(0.02)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    return True, out.read_text(encoding="utf-8", errors="replace")


def _swept(path: str, root: str) -> bool:
    git = os.path.join(os.path.realpath(root), ".git") + os.sep
    return not path.startswith(git) or path.startswith(os.path.join(git, "hooks") + os.sep)


def _with_pipe(path: Path):
    """Put a pipe at path. Return the undo."""
    keep = path.with_name(path.name + ".odd-keep")
    had = path.is_file() and not path.is_symlink()
    if had:
        os.replace(path, keep)
    elif path.is_symlink() or path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(path)

    def undo() -> None:
        if path.is_fifo():
            path.unlink()
        if had:
            os.replace(keep, path)

    return undo


def sweep(plan: dict, work: Path) -> dict:
    import cairnkit.cli  # noqa: F401  (once, before the forks)

    _offline()
    record = work / "opened.json"
    hung, out = _run(plan, work, record)
    if hung or not record.exists():
        return {"opened": [], "problems": {"(no pipe)": out[-2000:]}}
    opened = [p for p in json.loads(record.read_text(encoding="utf-8")) if _swept(p, plan["root"])]
    problems = {}
    for path in opened:
        undo = _with_pipe(Path(path))
        if undo is None:
            continue
        try:
            hung, out = _run(plan, work)
        finally:
            undo()
        if hung:
            problems[path] = "hung"
        elif "Traceback" in out:
            problems[path] = out[-2000:]
    return {"opened": opened, "problems": problems}


if __name__ == "__main__":
    plan_path, result_path = Path(sys.argv[1]), Path(sys.argv[2])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    result = sweep(plan, plan_path.parent)
    result_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
