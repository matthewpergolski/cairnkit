"""Count the words of a real session start that are not facts, once per adapter.

Nothing here reads a real memory or a real tool config: the repo, the memory, HOME and the XDG
folders are in a temporary folder. PATH gets one empty program per tool, so `memory init` connects
each adapter. With `--show`, it prints each line that is not a fact.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

AGENTS = ("claude", "codex", "cursor", "pi", "opencode", "grok")
AREAS = ("api", "billing", "deploy", "search", "auth", "ui")
KINDS = ("decision", "trap", "lesson", "fact")
TOPICS = (
    "The nightly export job writes to the replica, because the primary rejects long reads",
    "A retry on the payment webhook needs the original request id, or the charge runs twice",
    "Staging uses a separate search index, so a mapping change must run there first",
    "The session cookie is scoped to the parent domain, so a preview link shares the login",
    "The deploy script waits for the health check, and a slow cache warm can fail it",
    "The grid view reads the page size from local storage before the first request",
)
FACTS = 30


def cairn(root: Path, env: dict[str, str], *args: str, stdin: str = "") -> str:
    done = subprocess.run(
        [sys.executable, "-m", "cairnkit", *args],
        cwd=root,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def build(folder: Path) -> tuple[Path, dict[str, str]]:
    root = folder / "proj"
    root.mkdir()
    (folder / "home").mkdir()
    tools = folder / "bin"
    tools.mkdir()
    for name in AGENTS:
        program = tools / name
        program.write_text("#!/bin/sh\nexit 0\n")
        program.chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(folder / "home"),
        "XDG_CONFIG_HOME": str(folder / "config"),
        "XDG_CACHE_HOME": str(folder / "cache"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
    }
    env.pop("MEMORY_DIR", None)

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, env=env, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    (root / "README.md").write_text("bench\n")
    git("add", "-A")
    git("-c", "user.name=b", "-c", "user.email=b@example.invalid", "commit", "-q", "-m", "init")
    cairn(root, env, "init")
    for index in range(FACTS):
        cairn(
            root,
            env,
            "add",
            f"{TOPICS[index % len(TOPICS)]} (case {index}).",
            "--kind",
            KINDS[index % len(KINDS)],
            "--area",
            AREAS[index % len(AREAS)],
            "--basis",
            "seen",
            "--source",
            "session:2026-10-30",
        )
    return root, env


def model_text(root: Path, env: dict[str, str], agent: str) -> str:
    """What the model reads from one session start, in the form that this tool reads."""
    payload = json.dumps({"session_id": f"words-{agent}", "source": "startup"})
    out = cairn(root, env, "hook", "session-start", "--agent", agent, stdin=payload)
    if agent == "cursor":
        return json.loads(out)["additional_context"]
    if agent == "grok":
        # Grok shows a status line to the person. The load reaches the model at the first tool.
        after = json.dumps({"session_id": f"words-{agent}", "hook_event_name": "PostToolUse"})
        held = cairn(root, env, "hook", "after-shell", "--agent", agent, stdin=after)
        return json.loads(held)["hookSpecificOutput"]["additionalContext"]
    return out


def split(text: str) -> tuple[list[str], list[str]]:
    facts, other = [], []
    for line in text.splitlines():
        (facts if line.startswith("- [f-") else other).append(line)
    return facts, other


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="print each line that is not a fact")
    args = parser.parse_args()
    print(f"{'agent':>9} {'facts':>6} {'fact words':>11} {'other words':>12} {'total':>6}")
    failed = False
    with tempfile.TemporaryDirectory() as tmp:
        root, env = build(Path(tmp))
        for agent in AGENTS:
            facts, other = split(model_text(root, env, agent))
            fact_words = sum(len(line.split()) for line in facts)
            other_words = sum(len(line.split()) for line in other)
            print(
                f"{agent:>9} {len(facts):>6} {fact_words:>11} {other_words:>12} "
                f"{fact_words + other_words:>6}"
            )
            failed = failed or not facts
            if args.show:
                print("\n".join(f"    | {line}" for line in other if line.strip()))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
