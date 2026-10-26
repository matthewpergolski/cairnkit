"""`memory show` and `memory search`."""

from __future__ import annotations

import os
from pathlib import Path

from cairnkit import usage
from cairnkit.clock import now
from cairnkit.memory import Memory
from cairnkit.paths import LINK_NAME, merged_checker
from cairnkit.selection import FRAME_FOOTER, FRAME_HEADER, clean, render
from cairnkit.state import effective_status


def run_show(memory: Memory, fact_id: str) -> int:
    state = memory.states.get(fact_id)
    if state is None:
        print(f"error: no fact with id {fact_id}")
        return 1
    if state["status"] == "purged":
        print(f"{fact_id}: purged on {state.get('purged_at')} ({state.get('reason')}).")
        print("The content was removed for good.")
        return 0
    status, reason = effective_status(state, now(), merged_checker(memory.project.root))
    print(FRAME_HEADER)
    print(render(state))
    fields = (
        "kind",
        "area",
        "tags",
        "scope",
        "source",
        "author",
        "learned_at",
        "writer",
        "expires_at",
        "until_branch_merged",
        "pinned",
        "enforced_by",
    )
    for name in fields:
        if name in state:
            print(f"  {name}: {clean(state[name])}")
    for link in state.get("links", []):
        print(f"  link: {clean(link['rel'])} {clean(link['id'])}")
    print("History:")
    print(f"  {state.get('learned_at')}  created (active) by {state.get('writer')}")
    for change in state["history"]:
        parts = []
        if "status" in change:
            parts.append(change["status"])
        if "scope" in change:
            parts.append(f"scope {change['scope']}")
        if "superseded_by" in change:
            parts.append(f"by {change['superseded_by']}")
        if "held_by" in change:
            parts.append(f"held by {change['held_by']}")
        if "enforced_by" in change:
            value = change["enforced_by"]
            parts.append(f"enforced by {value}" if value else "advisory")
        for link in change.get("add_links", []):
            parts.append(f"link {link['rel']} {link['id']}")
        why = f": {clean(change['reason'])}" if change.get("reason") else ""
        print(f"  {change.get('at')}  {', '.join(parts)}{why} ({clean(change.get('writer'))})")
    computed = " (computed at read time)" if status != state["status"] else ""
    print(f"Now: {status}{computed}" + (f": {clean(reason)}" if reason else ""))
    print(FRAME_FOOTER)
    if status == "active":
        usage.record(memory, [fact_id], now())
    return 0


NOTE_SUFFIXES = {".md", ".markdown", ".txt"}
NOTE_LINES = 5  # note lines shown per search
NOTE_WIDTH = 120  # characters shown of one note line


def note_files(folder: Path) -> list[Path]:
    """The text files under notes/. Links are not followed, so nothing outside is read."""
    if folder.is_symlink() or not folder.is_dir():
        return []
    found = []
    for dirpath, _, filenames in os.walk(folder):  # does not descend into a linked folder
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in NOTE_SUFFIXES and not path.is_symlink() and path.is_file():
                found.append(path)
    return sorted(found)


def note_hits(memory: Memory, terms: list[str]) -> list[str]:
    """Lines of notes/ that hold every term, as `memory-bank/notes/PATH:LINE: text`."""
    folder = memory.dir / "notes"
    hits = []
    for path in note_files(folder):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, raw in enumerate(text.splitlines(), start=1):
            line = clean(raw)
            low = line.lower()
            if not all(term in low for term in terms):
                continue
            if len(line) > NOTE_WIDTH:
                start = max(0, min(low.find(terms[0]) - NOTE_WIDTH // 3, len(line) - NOTE_WIDTH))
                end = start + NOTE_WIDTH
                more = "..." if end < len(line) else ""
                line = ("..." if start else "") + line[start:end] + more
            rel = path.relative_to(folder).as_posix()
            hits.append(f"- {LINK_NAME}/notes/{rel}:{number}: {line}")
    return hits


def run_search(memory: Memory, query: str, include_all: bool, limit: int) -> int:
    terms = [t for t in query.lower().split() if t]
    moment = now()
    is_merged = merged_checker(memory.project.root)
    hits = []
    for state in memory.states.values():
        if state["status"] == "purged":
            continue
        status, reason = effective_status(state, moment, is_merged)
        if status != "active" and not include_all:
            continue
        hay = " ".join(
            [
                state.get("id", ""),
                state.get("text", ""),
                state.get("area", ""),
                " ".join(state.get("tags", [])),
                " ".join(c.get("reason", "") for c in state["history"]),
            ]
        ).lower()
        if all(term in hay for term in terms):
            hits.append(
                (
                    sum(hay.count(t) for t in terms),
                    state.get("learned_at", ""),
                    state,
                    status,
                    reason,
                )
            )
    notes = note_hits(memory, terms) if terms else []
    if not hits and not notes:
        scope = "any fact or note" if include_all else "active facts or notes (try --all)"
        print(f"no match for {query!r} in {scope}")
        return 0
    hits.sort(key=lambda h: (h[0], h[1]), reverse=True)  # most hits, then newest
    usage.record(memory, [h[2]["id"] for h in hits[:limit] if h[3] == "active"], moment)
    print(FRAME_HEADER)
    for _, _, state, status, reason in hits[:limit]:
        line = render(state)
        if status != "active":
            line += f" [{status}" + (f": {clean(reason)}" if reason else "") + "]"
        print(line)
    for line in notes[:NOTE_LINES]:
        print(line)
    print(FRAME_FOOTER)
    if len(hits) > limit:
        print(f"{len(hits) - limit} more; use --limit")
    if len(notes) > NOTE_LINES:
        print(f"{len(notes) - NOTE_LINES} more line(s) in notes")
    return 0
