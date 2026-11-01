"""Measure what the look for a new agent tool adds to a session start.

The repo, the memory, HOME and the XDG folders are in a temporary folder. PATH stays as it is,
because its length is the cost: the look searches PATH once per tool. It writes nothing there.

Run with `--child` inside that repo, it prints one JSON result.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def child(runs: int) -> None:
    from cairnkit import adapters, hooks_cmd
    from cairnkit.paths import find_project, resolve_memory_dir

    project = find_project()
    memdir, _ = resolve_memory_dir(project, None)
    seen = memdir / hooks_cmd.SEEN_FILE
    assert seen.is_file(), "the quiet path needs the record"
    quiet = []
    for _ in range(runs):
        start = time.perf_counter()
        hooks_cmd.connect_new_tools(project, None)
        quiet.append(time.perf_counter() - start)
    connected = []
    for _ in range(5):
        seen.write_text("[]\n", encoding="utf-8")
        for adapter in adapters.ADAPTERS.values():
            (project.main_root / adapter.rel).unlink(missing_ok=True)
        start = time.perf_counter()
        hooks_cmd.connect_new_tools(project, None)
        connected.append(time.perf_counter() - start)
    found = len([n for n in adapters.detect(project) if n != "generic"])
    print(
        json.dumps(
            {
                "quiet_median_ms": statistics.median(quiet) * 1000,
                "quiet_max_ms": max(quiet) * 1000,
                "connect_median_ms": statistics.median(connected) * 1000,
                "tools_found": found,
                "path_entries": len(os.environ["PATH"].split(os.pathsep)),
            }
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=500)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(args.runs)
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        root = folder / "proj"
        root.mkdir()
        (folder / "home").mkdir()
        env = {
            **os.environ,
            "HOME": str(folder / "home"),
            "XDG_CONFIG_HOME": str(folder / "config"),
            "XDG_CACHE_HOME": str(folder / "cache"),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        env.pop("MEMORY_DIR", None)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, env=env, check=True)
        subprocess.run(
            [sys.executable, "-m", "cairnkit", "init"],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
        )
        done = subprocess.run(
            [sys.executable, __file__, "--child", "--runs", str(args.runs)],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    print(done.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
