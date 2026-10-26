"""`memory show` and `memory search`."""

from __future__ import annotations

import os
from pathlib import Path

from cairnkit import ranking, usage
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
USE_SHARE = 0.8  # a hit counts as use when its score is this share of the best score


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


def note_hits(memory: Memory, terms: list[str], strict: bool = False) -> list[str]:
    """Lines of notes/ as `memory-bank/notes/PATH:LINE: text`, best first.

    A line counts when it holds any term (BM25 over the lines). With `strict`, it must
    hold every term, as a substring, and the lines come in file order.
    """
    folder = memory.dir / "notes"
    lines = []  # (path, number, cleaned line)
    for path in note_files(folder):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, raw in enumerate(text.splitlines(), start=1):
            line = clean(raw)
            if line.strip():
                lines.append((path.relative_to(folder).as_posix(), number, line))
    if strict:
        picked = [
            (rel, n, line, 0.0) for rel, n, line in lines if all(t in line.lower() for t in terms)
        ]
    else:
        scores = ranking.bm25([line for _, _, line in lines], terms)
        picked = [
            (rel, n, line, round(s, 9))
            for (rel, n, line), s in zip(lines, scores, strict=True)
            if s > 0
        ]
        picked.sort(key=lambda p: (-p[3], p[0], p[1]))
    return [
        f"- {LINK_NAME}/notes/{rel}:{n}: {_snippet(line, terms, strict)}"
        for rel, n, line, _ in picked
    ]


def _snippet(line: str, terms: list[str], strict: bool) -> str:
    """The line, cut to NOTE_WIDTH characters around the first query word it holds."""
    if len(line) <= NOTE_WIDTH:
        return line
    low = line.lower()
    if strict:
        at = low.find(terms[0])
    else:
        at = next(
            (m.start() for m in ranking.WORD.finditer(low) if ranking.stem(m.group()) in terms), 0
        )
    start = max(0, min(at - NOTE_WIDTH // 3, len(line) - NOTE_WIDTH))
    end = start + NOTE_WIDTH
    more = "..." if end < len(line) else ""
    return ("..." if start else "") + line[start:end] + more


def run_search(
    memory: Memory, query: str, include_all: bool, limit: int, strict: bool = False
) -> int:
    if strict:
        terms = [t for t in query.lower().split() if t]
    else:
        terms = ranking.query_terms(query)
        if not terms:
            print(f"error: no searchable words in {query!r}")
            return 1
    moment = now()
    is_merged = merged_checker(memory.project.root)
    shown = []  # (state, status, reason) of every fact that may match
    for state in memory.states.values():
        if state["status"] == "purged":
            continue
        status, reason = effective_status(state, moment, is_merged)
        if status != "active" and not include_all:
            continue
        shown.append((state, status, reason))
    by_id = {s["id"]: (status, reason) for s, status, reason in shown}
    states = [s for s, _, _ in shown]
    ranked = ranking.rank_strict(states, query) if strict else ranking.rank_facts(states, terms)
    hits = [(state, *by_id[state["id"]]) for state, _ in ranked]
    best = ranked[0][1] if ranked else 0.0
    notes = note_hits(memory, terms, strict) if terms else []
    if not hits and not notes:
        scope = "any fact or note" if include_all else "active facts or notes (try --all)"
        hint = "" if strict else "; --strict matches parts of words"
        print(f"no match for {query!r} in {scope}{hint}")
        return 0
    used = [  # a loose match is not use: only the facts near the top score count
        state["id"]
        for (state, status, _), (_, score) in zip(hits[:limit], ranked, strict=False)
        if status == "active" and (strict or score >= USE_SHARE * best)
    ]
    usage.record(memory, used, moment)
    print(FRAME_HEADER)
    for state, status, reason in hits[:limit]:
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
