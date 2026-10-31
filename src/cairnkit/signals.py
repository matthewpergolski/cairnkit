"""Events that a session should hear about. The tool names them. The agent decides.

Nothing here writes a fact, so no text from the tool can load as memory. The state lives in the
session file (see session.py). Each event is reported once.
"""

from __future__ import annotations

import re

from cairnkit.clock import now, parse_time
from cairnkit.load import active_states, changed_paths
from cairnkit.memory import Memory
from cairnkit.paths import current_branch, run_git, writer_name
from cairnkit.selection import areas_for_paths, clean, load_text, score_parts
from cairnkit.session import load_state, save_state

FIX_MIN_FAILS = 2
MAX_LINES = 5
REVERT = re.compile(r"(?i)^(revert\b|.*\breverts?\b)")


def note_command(memory: Memory, key: str, command: str, ok: bool) -> None:
    """Count a failure. A pass after repeated failures is a fix worth a fact."""
    state = load_state(memory, key)
    if state is None:
        return
    fails = state.setdefault("fails", {})
    if not ok:
        fails[command] = fails.get(command, 0) + 1
    elif fails.get(command, 0) >= FIX_MIN_FAILS:
        state.setdefault("fixed", []).append([command, fails.pop(command)])
    else:
        fails.pop(command, None)
    save_state(memory, key, state)


def _reverts(root, state: dict) -> list[str]:
    start = state.get("start_head")
    if not start:
        return []
    log = run_git(root, "log", "--format=%h %s", f"{start}..HEAD", timeout=2.0) or ""
    return [
        line for line in log.splitlines() if " " in line and REVERT.match(line.split(" ", 1)[1])
    ]


def session_events(memory: Memory, key: str) -> list[str]:
    """New events that a later session may need. Each one is returned once."""
    state = load_state(memory, key)
    if state is None:
        return []
    told = state.setdefault("told", [])
    found = []
    for command, count in state.get("fixed", []):
        found.append(f"`{command}` failed {count} times, then passed. What fixed it?")
    for command, count in state.get("fails", {}).items():
        if count >= FIX_MIN_FAILS:
            found.append(f"`{command}` failed {count} times and has not passed.")
    for line in _reverts(memory.project.root, state):
        found.append(f"A revert: {line}. Why did the first attempt not hold?")
    fresh = [line for line in found if line not in told]
    if fresh:
        told.extend(fresh)
        save_state(memory, key, state)
    return fresh


def _since(record: dict) -> str | None:
    return record.get("learned_at") if record.get("type") == "fact" else record.get("at")


def _changed_elsewhere(memory: Memory, mark: str, heard: list[str]) -> list[str]:
    """Facts that another branch or auto-tidy wrote or ended after this session loaded.

    Times have one-second steps, so a record in the same second counts. `heard` stops a repeat.
    """
    mine = writer_name(memory.project.root)
    since = parse_time(mark)
    lines = []
    for record in memory.records:
        when = _since(record)
        if not when or record.get("writer") == mine:
            continue
        try:
            if parse_time(when) < since:
                continue
        except ValueError:
            continue
        state = memory.states.get(record.get("id"))
        if not state:
            continue
        label = "new" if record.get("type") == "fact" else record.get("status")
        key = f"{label}:{state['id']}"
        if label and key not in heard:
            heard.append(key)
            lines.append(f"- {label} [{state['id']}] {clean(load_text(state))}")
    return lines


def _now_relevant(memory: Memory, state: dict) -> tuple[list[str], list[str]]:
    """Facts that match the files changed since the load and did not show. Traps first."""
    root = memory.project.root
    areas = areas_for_paths(changed_paths(root, current_branch(root)), memory.config["areas"])
    known = set(state.get("areas", []))
    if not areas - known:
        return [], sorted(known | areas)
    moment = now()
    new = areas - known
    shown = set(state.get("shown", []))
    rows = []
    for fact in active_states(memory):
        if fact["id"] in shown or fact.get("kind") == "rule":
            continue
        parts = score_parts(fact, moment, new, set())
        if parts["area"] or parts["mention"]:
            rows.append((-(parts["trap"] + parts["area"] + parts["recency"]), fact["id"], fact))
    rows.sort(key=lambda row: row[:2])
    picked = [row[2] for row in rows[:MAX_LINES]]
    state["shown"] = sorted(shown | {fact["id"] for fact in picked})
    lines = [f"- [{fact['id']}] {clean(load_text(fact))}" for fact in picked]
    return lines, sorted(known | areas)


def news(memory: Memory, key: str) -> str | None:
    """What changed in the memory or in the work since this session last heard. Once each."""
    state = load_state(memory, key)
    if state is None or not state.get("loaded_at"):
        return None
    parts = []
    if state.pop("compacted", False):
        parts.append("Context was compacted. Run `memory load` to read the memory again.")
    elsewhere = _changed_elsewhere(memory, state["loaded_at"], state.setdefault("heard", []))
    if elsewhere:
        parts.append("Memory changed on another branch:\n" + "\n".join(elsewhere[:MAX_LINES]))
    relevant, areas = _now_relevant(memory, state)
    state["areas"] = areas
    if relevant:
        parts.append("These stored facts match the files you changed:\n" + "\n".join(relevant))
    save_state(memory, key, state)
    return "\n\n".join(parts) or None
