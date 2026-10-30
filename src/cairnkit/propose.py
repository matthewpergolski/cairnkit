"""Draft pending fact candidates from local git events. No network, no model.

Three passes, same pending store (`proposals/auto-candidates.jsonl`):

- `draft` (post-commit): under ~1s. Commit message + changed paths / short
  hunks → candidate texts with kind hints.
- `fuller` (pre-push / post-merge): bounded by the git-hook budget. Prefers
  lessons, decisions, and traps; skips near-dupes of active facts.
- `stop_fallback`: when a session ends with the same HEAD it started on
  (no commit this session), draft from durable dirty paths.

Pending candidates are never injected into load. Accept goes through
`memory add` validation.
"""

from __future__ import annotations

import re
from pathlib import Path

from cairnkit.clock import now, stamp
from cairnkit.memory import Memory, MemoryMissing
from cairnkit.paths import Project, run_git
from cairnkit.pending import Candidate, add_candidates, unique_id
from cairnkit.secretscan import find_secrets
from cairnkit.similar import analyze, similarity
from cairnkit.state import effective_status

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
KIND_WORDS = (
    ("decision", "decision"),
    ("decide", "decision"),
    ("chose", "decision"),
    ("trap", "trap"),
    ("gotcha", "trap"),
    ("pitfall", "trap"),
    ("lesson", "lesson"),
    ("learned", "lesson"),
    ("prefer", "fact"),
    ("always", "fact"),
    ("never", "trap"),
)
PREFERRED = frozenset({"lesson", "decision", "trap"})
MIN_TEXT = 24
MAX_TEXT = 400
MAX_HUNK = 40
MAX_DRAFT = 5
MAX_FULLER = 12


def _kind_hint(text: str) -> str:
    lower = text.lower()
    for word, kind in KIND_WORDS:
        if word in lower:
            return kind
    return "fact"


def _clean(text: str) -> str:
    text = " ".join(text.strip().split())
    text = re.sub(r"^(feat|fix|test|chore|docs|refactor|ci)(\([^)]*\))?:\s*", "", text, flags=re.I)
    return text.strip(" -:")


def _area_from_paths(paths: list[str]) -> str:
    if not paths:
        return "general"
    top = Path(paths[0]).parts[0] if paths[0] else "general"
    if top in (".", ""):
        return "general"
    return re.sub(r"[^a-z0-9_-]+", "-", top.lower())[:40] or "general"


def _parent_commit(root: Path, head: str) -> str:
    parent = run_git(root, "rev-parse", "--verify", f"{head}^", timeout=1.0)
    return parent or EMPTY_TREE


def _commit_meta(root: Path, head: str) -> tuple[str, list[str], str]:
    """Return (subject, paths, short_diff) for one commit."""
    subject = run_git(root, "log", "-1", "--format=%s", head, timeout=1.0) or ""
    paths_out = run_git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", head, timeout=1.0)
    paths = [p for p in (paths_out or "").splitlines() if p]
    parent = _parent_commit(root, head)
    diff = (
        run_git(
            root,
            "diff",
            "--unified=1",
            parent,
            head,
            "--",
            *paths[:20],
            timeout=1.0,
        )
        or ""
    )
    lines = []
    for line in diff.splitlines():
        if line.startswith(("+++", "---", "diff ", "index ", "@@")):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:].strip())
        if len(lines) >= MAX_HUNK:
            break
    return subject, paths, "\n".join(lines)


def _from_message(subject: str) -> list[tuple[str, str]]:
    text = _clean(subject)
    if len(text) < MIN_TEXT or len(text) > MAX_TEXT:
        return []
    if find_secrets(text):
        return []
    return [(text, _kind_hint(subject))]


def _from_hunks(hunk: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for raw in hunk.splitlines():
        line = _clean(raw.lstrip("#/").strip())
        if len(line) < MIN_TEXT or len(line) > MAX_TEXT:
            continue
        lower = line.lower()
        if not any(word in lower for word, _ in KIND_WORDS):
            continue
        if find_secrets(line):
            continue
        found.append((line, _kind_hint(line)))
        if len(found) >= 3:
            break
    return found


def _candidates_for_commit(
    memory: Memory, head: str, *, origin: str, prefer: bool
) -> list[Candidate]:
    root = memory.project.root
    subject, paths, hunk = _commit_meta(root, head)
    pairs = _from_message(subject) + _from_hunks(hunk)
    if prefer:
        pairs = [p for p in pairs if p[1] in PREFERRED] or pairs
    source = f"commit:{head[:12]}"
    area = _area_from_paths(paths)
    out: list[Candidate] = []
    seen: set[str] = set()
    for text, kind in pairs:
        key = " ".join(text.lower().split())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Candidate(
                id=unique_id(memory, text, source),
                text=text,
                kind=kind,
                source=source,
                origin=origin,
                area=area,
                created_at=stamp(now()),
                commit=head[:40],
                paths=paths[:20],
            )
        )
    return out


def near_active(memory: Memory, text: str) -> bool:
    """True when an active fact is a near or exact duplicate of text."""
    words = analyze(text)
    moment = now()
    for state in memory.states.values():
        if state.get("status") != "active":
            continue
        if effective_status(state, moment, None)[0] != "active":
            continue
        score = similarity(words, analyze(str(state.get("text", ""))))
        if score is not None:
            return True
    return False


def draft_from_head(memory: Memory) -> list[Candidate]:
    """Fast draft from HEAD~1..HEAD (or empty-tree for the root commit)."""
    root = memory.project.root
    head = run_git(root, "rev-parse", "HEAD", timeout=1.0)
    if not head:
        return []
    items = _candidates_for_commit(memory, head, origin="draft", prefer=False)
    added = add_candidates(memory, items[:MAX_DRAFT])
    from cairnkit import autogate

    autogate.note_pending(memory, len(added))
    return added


def fuller_propose(memory: Memory) -> list[Candidate]:
    """Richer pass over recent commits. Skips near-dupes of active facts."""
    root = memory.project.root
    log = run_git(root, "log", "-8", "--format=%H", timeout=1.5) or ""
    heads = [h for h in log.splitlines() if h]
    collected: list[Candidate] = []
    for head in heads:
        for item in _candidates_for_commit(memory, head, origin="fuller", prefer=True):
            if near_active(memory, item.text):
                continue
            if item.kind not in PREFERRED and len(collected) >= MAX_FULLER // 2:
                continue
            collected.append(item)
            if len(collected) >= MAX_FULLER:
                break
        if len(collected) >= MAX_FULLER:
            break
    added = add_candidates(memory, collected)
    from cairnkit import autogate

    autogate.note_pending(memory, len(added))
    return added


def _dirty_paths(root: Path) -> list[str]:
    out = run_git(root, "status", "--porcelain", timeout=1.0) or ""
    paths = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path and not path.startswith(("memory-bank", ".")):
            paths.append(path)
    return paths[:30]


def stop_fallback(memory: Memory, start_head: str | None) -> list[Candidate]:
    """Propose from dirty paths when the session made no commit."""
    root = memory.project.root
    head = run_git(root, "rev-parse", "HEAD", timeout=1.0) or ""
    if start_head and head and start_head == head:
        pass
    elif start_head and head and start_head != head:
        return []
    paths = _dirty_paths(root)
    if not paths:
        return []
    # Prefer a short note from the first durable path name + status.
    texts: list[tuple[str, str]] = []
    for path in paths[:5]:
        name = Path(path).name
        text = _clean(f"working change in {path}: review before the next session")
        if len(text) >= MIN_TEXT:
            texts.append((text, "fact"))
        stem = _clean(name.replace("_", " ").replace("-", " "))
        if len(stem) >= MIN_TEXT:
            texts.append((stem, _kind_hint(stem)))
    source = f"file:{paths[0]}" if paths else "session:stop"
    area = _area_from_paths(paths)
    items = []
    for text, kind in texts[:3]:
        if find_secrets(text) or near_active(memory, text):
            continue
        items.append(
            Candidate(
                id=unique_id(memory, text, source),
                text=text,
                kind=kind,
                source=source if source.startswith("file:") else f"session:{stamp(now())[:10]}",
                origin="stop_fallback",
                area=area,
                created_at=stamp(now()),
                commit=head[:40] or None,
                paths=paths[:20],
            )
        )
    return add_candidates(memory, items)


def run_draft(project: Project, flag: str | None) -> int:
    try:
        memory = Memory.open(project, flag)
        draft_from_head(memory)
    except (MemoryMissing, Exception):
        pass
    return 0


def run_fuller(project: Project, flag: str | None) -> int:
    try:
        memory = Memory.open(project, flag)
        fuller_propose(memory)
    except (MemoryMissing, Exception):
        pass
    return 0


def run_stop_fallback(project: Project, flag: str | None, start_head: str | None) -> int:
    try:
        memory = Memory.open(project, flag)
        stop_fallback(memory, start_head)
    except (MemoryMissing, Exception):
        pass
    return 0
