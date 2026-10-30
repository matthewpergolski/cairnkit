"""Session state for hooks: what changed since the session started.

The state lives in `<memory>/.sessions/<id>.json`. It is local, small and safe
to delete.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cairnkit.autotidy import WRITER as AUTO_TIDY_WRITER
from cairnkit.clock import now, parse_time, stamp
from cairnkit.install_source import SKIP_DIRS, SKIP_SUFFIXES
from cairnkit.memory import Memory
from cairnkit.paths import run_git

KEEP_DAYS = 7
GATE = "durable"
JUNK_DIRS = frozenset(SKIP_DIRS) | {
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".eggs",
    "coverage",
    ".idea",
    ".vscode",
}
JUNK_SUFFIXES = (*SKIP_SUFFIXES, ".orig", ".rej")
JUNK_NAMES = frozenset({".DS_Store", "Thumbs.db"})
SOURCE_NAMES = frozenset(
    {"Makefile", "Dockerfile", "Containerfile", "justfile", "Rakefile", "Gemfile"}
)
SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".toml",
        ".md",
        ".rst",
        ".txt",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".php",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".yml",
        ".yaml",
        ".json",
        ".css",
        ".html",
        ".vue",
        ".svelte",
        ".gradle",
        ".cs",
        ".fs",
        ".swift",
    }
)


def _path(memory: Memory, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", session_id or "default")[:80] or "default"
    return memory.dir / ".sessions" / f"{safe}.json"


def _inside_repo(root: Path, folder: Path | None) -> str | None:
    if folder is None:
        return None
    try:
        rel = Path(folder).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return None
    text = rel.as_posix()
    if text in ("", "."):
        return None
    return text


def _pathspecs(root: Path, memory_dir: Path | None) -> list[str]:
    specs = [".", ":(exclude)memory-bank", ":(exclude).memory-path"]
    rel = _inside_repo(root, memory_dir)
    if rel:
        specs.append(f":(exclude){rel}")
    return specs


def _memory_path(path: str, root: Path, memory_dir: Path | None) -> bool:
    norm = path.replace("\\", "/")
    if norm in ("memory-bank", ".memory-path") or norm.startswith(
        ("memory-bank/", ".memory-path/")
    ):
        return True
    rel = _inside_repo(root, memory_dir)
    return bool(rel and (norm == rel or norm.startswith(rel + "/")))


def _untracked_paths(root: Path) -> list[str]:
    out = run_git(root, "status", "--porcelain", "--untracked-files=all", timeout=2.0) or ""
    found = []
    for line in out.splitlines():
        if len(line) < 4 or line[:2] != "??":
            continue
        raw = line[3:]
        if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
            raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if raw:
            found.append(raw)
    return found


def is_junk_path(path: str) -> bool:
    """True when a path is filler (.log, caches, editor debris), tracked or not."""
    parts = PurePosixPath(path).parts
    if not parts or any(part in JUNK_DIRS for part in parts):
        return True
    name = parts[-1]
    return name in JUNK_NAMES or name.endswith(JUNK_SUFFIXES)


def durable_untracked(path: str) -> bool:
    """True when an untracked path is source worth a stop reminder."""
    if is_junk_path(path):
        return False
    name = PurePosixPath(path).name
    if name in SOURCE_NAMES:
        return True
    return PurePosixPath(name).suffix.lower() in SOURCE_SUFFIXES


def _durable_tracked_paths(root: Path, memory_dir: Path | None) -> list[str]:
    """Tracked paths that changed under HEAD, minus memory and junk."""
    specs = _pathspecs(root, memory_dir)
    listed = run_git(root, "diff", "--name-only", "HEAD", "--", *specs, timeout=2.0) or ""
    paths = []
    for path in listed.splitlines():
        if not path or _memory_path(path, root, memory_dir) or is_junk_path(path):
            continue
        if path not in paths:
            paths.append(path)
    return paths


@dataclass(frozen=True)
class DurableSnapshot:
    """The part of the worktree a later session could need a fact about."""

    head: str
    tracked_diff: str
    untracked: tuple[str, ...]

    def digest(self) -> str:
        blob = "\0".join(("durable-v1", self.head, self.tracked_diff, *self.untracked))
        return hashlib.sha1(blob.encode()).hexdigest()


class ReminderGate:
    """Whether stop should ask for a memory write. Junk files do not count."""

    def snapshot(self, root: Path, memory_dir: Path | None = None) -> DurableSnapshot:
        head = run_git(root, "rev-parse", "HEAD", timeout=2.0) or ""
        durable = _durable_tracked_paths(root, memory_dir)
        tracked = (
            (run_git(root, "diff", "HEAD", "--", *durable, timeout=2.0) or "") if durable else ""
        )
        untracked = tuple(
            sorted(
                path
                for path in _untracked_paths(root)
                if durable_untracked(path) and not _memory_path(path, root, memory_dir)
            )
        )
        return DurableSnapshot(head, tracked, untracked)

    def names(self, root: Path, memory_dir: Path | None = None) -> list[str]:
        names = list(_durable_tracked_paths(root, memory_dir))
        for path in self.snapshot(root, memory_dir).untracked:
            if path not in names:
                names.append(path)
        return names


def fingerprint(root: Path, memory_dir: Path | None = None) -> str:
    """A hash of the durable snapshot. Junk and unchanged trees keep the same hash."""
    return ReminderGate().snapshot(root, memory_dir).digest()


def reminder_text(memory: Memory) -> str:
    """The stop message. It names the durable paths and says the agent may finish."""
    root = memory.project.root
    gate = ReminderGate()
    snap = gate.snapshot(root, memory.dir)
    names = gate.names(root, memory.dir)
    if names:
        lines = [f"- {name}" for name in names[:5]]
        if len(names) > 5:
            lines.append(f"- and {len(names) - 5} more")
        listing = "\n".join(lines)
    else:
        listing = f"- new commit {(snap.head or 'unknown')[:7]}"
    return (
        "Tracked work changed and no fact was written.\n"
        f"{listing}\n"
        "Search before adding: `memory search WORDS`. Open a hit with `memory show ID`.\n"
        "Record what a later session needs:\n"
        "- a decision, trap, or lesson: "
        '`memory add "TEXT" --kind decision|trap|lesson --area AREA '
        "--basis seen|told|guess --source commit:HASH|file:PATH`\n"
        "- a note for this branch only: "
        '`memory add "TEXT" --short --until-merged --area AREA '
        "--basis seen --source session:DATE`\n"
        "- a fact that is now wrong: "
        '`memory change ID --status wrong|expired --reason "..."` '
        'or `memory add "TEXT" --supersedes ID`\n'
        "If none of this is worth a fact, say so and finish."
    )


def load_state(memory: Memory, session_id: str) -> dict | None:
    try:
        return json.loads(_path(memory, session_id).read_text())
    except (OSError, ValueError):
        return None


def save_state(memory: Memory, session_id: str, state: dict) -> None:
    path = _path(memory, session_id)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(state))
    _prune(path.parent)


def _prune(folder: Path) -> None:
    limit = time.time() - KEEP_DAYS * 86400
    for old in folder.glob("*.json"):
        try:
            if old.stat().st_mtime < limit:
                old.unlink()
        except OSError:
            pass


def start_session(memory: Memory, session_id: str) -> None:
    head = run_git(memory.project.root, "rev-parse", "HEAD", timeout=2.0) or ""
    save_state(
        memory,
        session_id,
        {
            "started_at": stamp(now()),
            "start": fingerprint(memory.project.root, memory.dir),
            "start_head": head,
            "gate": GATE,
        },
    )


def wrote_since(memory: Memory, moment: str) -> bool:
    since = parse_time(moment)
    for rec in memory.records:
        if rec.get("writer") == AUTO_TIDY_WRITER:
            continue
        when = rec.get("learned_at") if rec.get("type") == "fact" else rec.get("at")
        try:
            if when and parse_time(when) >= since:
                return True
        except ValueError:
            continue
    return False


def needs_reminder(memory: Memory, session_id: str) -> bool:
    """True once per new durable snapshot, when no agent fact was written for it."""
    state = load_state(memory, session_id)
    current = fingerprint(memory.project.root, memory.dir)
    if state is None or state.get("gate") != GATE:
        start_session(memory, session_id)
        return False
    if current in (state.get("start"), state.get("reminded")):
        return False
    if wrote_since(memory, state.get("reminded_at") or state["started_at"]):
        return False
    state["reminded"] = current
    state["reminded_at"] = stamp(now())
    state["gate"] = GATE
    save_state(memory, session_id, state)
    return True


def note_failure(memory: Memory, session_id: str, command: str) -> str | None:
    """Record one failed shell/tool command for the loop breaker.

    `session_id` is kept for callers that key failures per session; the streak
    itself is global to the memory folder (same command across tools).
    Returns the nudge text when the streak hits three, else None.
    """
    from cairnkit import loopbreak

    _ = session_id  # reserved: per-session streaks if a later harness needs them
    return loopbreak.observe(memory, command, ok=False)


def loop_nudge(memory: Memory) -> str | None:
    """Nudge text when the current fail streak is at the threshold."""
    from cairnkit import loopbreak

    data = loopbreak._load(memory)
    if int(data.get("streak", 0)) >= loopbreak.THRESHOLD and data.get("command"):
        return loopbreak.NUDGE
    return None
