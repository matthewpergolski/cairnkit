"""Time the real session-start hook on a throwaway memory with many varied facts.

Nothing here reads a real memory folder: the repo, the memory and HOME are in a temporary folder.
Each size has a known number of near repeats. The script fails when the hook reports fewer, so a
fast run that skipped the work does not count.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import resource
import statistics
import string
import subprocess
import sys
import tempfile
import time
from pathlib import Path

NEAR_REPEATS = 5
SESSION_BUDGET_SECONDS = 10


def varied_text(rng: random.Random, vocabulary: list[str], words: int) -> str:
    return " ".join(rng.choice(vocabulary) for _ in range(words))


def fact_lines(count: int, vocabulary_size: int, seed: int = 0) -> list[str]:
    """`count` varied facts, then one newer near repeat of each of the last NEAR_REPEATS."""
    rng = random.Random(seed)
    vocabulary = [
        "".join(letters) for letters in itertools.product(string.ascii_lowercase, repeat=3)
    ][:vocabulary_size]
    texts = [varied_text(rng, vocabulary, 20) for _ in range(count)]
    lines = [fact_line(i, text) for i, text in enumerate(texts)]
    for i, text in enumerate(texts[-NEAR_REPEATS:]):
        lines.append(fact_line(count + i, f"the {text}", day=20))
    return lines


def fact_line(index: int, text: str, day: int = 1) -> str:
    return json.dumps(
        {
            "type": "fact",
            "id": f"f-202610{day:02d}-{index:05x}",
            "kind": "fact",
            "text": text,
            "area": f"area{index % 12}",
            "happened_at": f"2026-10-{day:02d}",
            "learned_at": f"2026-10-{day:02d}T12:00:00+00:00",
            "source": "session:bench",
            "basis": "seen",
            "status": "active",
            "scope": "long",
            "writer": "main",
        }
    )


def build(folder: Path, lines: list[str]) -> tuple[Path, dict[str, str]]:
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

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (root / "README.md").write_text("bench\n")
    git("add", "-A")
    git("-c", "user.name=b", "-c", "user.email=b@example.invalid", "commit", "-q", "-m", "init")
    cairn = [sys.executable, "-m", "cairnkit"]
    subprocess.run(
        [*cairn, "init", "--no-default-rules"], cwd=root, env=env, check=True, capture_output=True
    )
    (folder / "proj.memory" / "facts" / "main.jsonl").write_text("\n".join(lines) + "\n")
    return root, env


def child_cpu() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def run_once(root: Path, env: dict[str, str]) -> tuple[float, float, str]:
    start, cpu = time.perf_counter(), child_cpu()
    done = subprocess.run(
        [sys.executable, "-m", "cairnkit", "hook", "session-start", "--agent", "claude"],
        cwd=root,
        env=env,
        input='{"session_id": "bench"}',
        capture_output=True,
        text=True,
        check=True,
    )
    return time.perf_counter() - start, child_cpu() - cpu, done.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=int, nargs="+", default=[200, 1000, 2000])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--vocabulary",
        type=int,
        default=3000,
        help="distinct words; a small one makes the prefix filter work hardest",
    )
    args = parser.parse_args()
    print(
        f"{'facts':>6} {'runs':>5} {'median s':>9} {'min s':>7} {'max s':>7} "
        f"{'cpu s':>7} {'reported':>9}"
    )
    failed = False
    for count in args.facts:
        with tempfile.TemporaryDirectory() as tmp:
            root, env = build(Path(tmp), fact_lines(count, args.vocabulary))
            times, cpu, reported = [], [], set()
            for _ in range(args.runs):
                seconds, cpu_seconds, out = run_once(root, env)
                times.append(seconds)
                cpu.append(cpu_seconds)
                line = next((x for x in out.splitlines() if "would retire" in x), "")
                reported.add(line.split("would retire ")[1].split(":")[0] if line else "0")
        ok = min(int(n) for n in reported) >= NEAR_REPEATS
        failed = failed or not ok
        print(
            f"{count:>6} {args.runs:>5} {statistics.median(times):>9.3f} {min(times):>7.3f} "
            f"{max(times):>7.3f} {statistics.median(cpu):>7.3f} {','.join(sorted(reported)):>9}"
            f"{'' if ok else '  WRONG: the near repeats were not all found'}"
        )
    print(f"The hook timeout is {SESSION_BUDGET_SECONDS} s.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
