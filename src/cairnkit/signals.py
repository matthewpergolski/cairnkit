"""Events that a session should hear about. The tool names them. The agent decides.

Nothing here writes a fact, so no text from the tool can load as memory. The state lives in the
session file (see session.py). Each event is reported once.
"""

from __future__ import annotations

import re

from cairnkit import loopbreak
from cairnkit.clock import now, parse_time
from cairnkit.load import active_states, changed_paths
from cairnkit.memory import Memory
from cairnkit.paths import current_branch, run_git, writer_name
from cairnkit.selection import (
    DATA_LABEL,
    FRAME_FOOTER,
    FRAME_HEADER,
    areas_for_paths,
    clean,
    load_text,
    score_parts,
)
from cairnkit.session import load_state, loop_nudge, save_state

FIX_MIN_FAILS = 2
MAX_LINES = 5
REVERT = re.compile(r"(?i)^revert(?:s|ed)?\s|^revert(?:\([^)]*\))?!?:")
# Reflog actions that make a new commit in this checkout. A merge, a pull or a switch brings
# the commits of other people, so it is not here.
OWN_COMMIT = re.compile(r"^(commit|revert|cherry-pick)\b")
REFLOG_TIME = re.compile(r"@\{(\d+)\}")
REFLOG_LIMIT = "500"
COMMAND_WIDTH = 200


def _quoted(command: str) -> str:
    """A command in a code span that it cannot close."""
    flat = clean(command).replace("`", "'")
    cut = "..." if len(flat) > COMMAND_WIDTH else ""
    return f"`{flat[:COMMAND_WIDTH]}{cut}`"


def _fail_token(command: str) -> str:
    return f"fail:{command}"


def _loop_token(command: str) -> str:
    return f"loop:{command}"


def note_command(memory: Memory, key: str, command: str, ok: bool) -> None:
    """Count a failure. A pass after repeated failures is a fix worth a fact."""
    state = load_state(memory, key)
    if state is None:
        return
    fails = state.setdefault("fails", {})
    if not ok:
        fails[command] = fails.get(command, 0) + 1
    else:
        if fails.get(command, 0) >= FIX_MIN_FAILS:
            state.setdefault("fixed", []).append([command, fails[command]])
        fails.pop(command, None)
        ended = {_fail_token(command), _loop_token(command)}
        state["told"] = [token for token in state.get("told", []) if token not in ended]
    save_state(memory, key, state)


def note_nudge(memory: Memory, key: str, command: str) -> None:
    """The loop nudge reached the agent with the tool result. Stop does not repeat it."""
    state = load_state(memory, key)
    if state is not None:
        state.setdefault("told", []).append(_loop_token(command))
        save_state(memory, key, state)


def stop_nudge(memory: Memory, key: str) -> str | None:
    """The loop nudge for a stop, once for each run of failures."""
    text = loop_nudge(memory)
    state = load_state(memory, key)
    if text is None or state is None:
        return text
    token = _loop_token(loopbreak.current_command(memory))
    if token in state.get("told", []):
        return None
    state.setdefault("told", []).append(token)
    save_state(memory, key, state)
    return text


def _reverts(root, state: dict) -> list[str]:
    """Reverts that this checkout committed after the session started. The reflog knows."""
    started = state.get("started_at")
    if not started:
        return []
    since = parse_time(started).timestamp()
    log = run_git(
        root,
        "log",
        "-g",
        "-n",
        REFLOG_LIMIT,
        "--date=unix",
        "--format=%gd%x00%h%x00%gs%x00%s",
        "HEAD",
        timeout=2.0,
    )
    found = []
    for line in (log or "").splitlines():
        parts = line.split("\0", 3)
        moment = REFLOG_TIME.search(parts[0])
        if len(parts) != 4 or not moment or int(moment.group(1)) < since:
            continue
        if OWN_COMMIT.match(parts[2]) and REVERT.match(parts[3]):
            found.append(clean(f"{parts[1]} {parts[3]}"))
    return found


def session_events(memory: Memory, key: str) -> list[str]:
    """New events that a later session may need. Each one is returned once."""
    state = load_state(memory, key)
    if state is None:
        return []
    told = state.setdefault("told", [])
    found = []
    for number, (command, count) in enumerate(state.get("fixed", [])):
        shown = _quoted(loopbreak.without_secret(command, memory.env))
        line = f"{shown} failed {count} times, then passed. What fixed it?"
        found.append((f"fixed:{number}:{command}", line))
    for command, count in state.get("fails", {}).items():
        if count >= FIX_MIN_FAILS:
            shown = _quoted(loopbreak.without_secret(command, memory.env))
            line = f"{shown} failed {count} times and has not passed."
            found.append((_fail_token(command), line))
    for line in _reverts(memory.project.root, state):
        found.append((f"revert:{line}", f"A revert: {line}. Why did the first attempt not hold?"))
    fresh = [(token, line) for token, line in found if token not in told]
    if fresh:
        told.extend(token for token, _ in fresh)
        save_state(memory, key, state)
    return [line for _, line in fresh]


def _since(record: dict) -> str | None:
    return record.get("learned_at") if record.get("type") == "fact" else record.get("at")


def _for_this_branch(memory: Memory):
    """The same test as the load: a short note belongs to one branch."""
    root = memory.project.root
    branch, writer = current_branch(root), writer_name(root)

    def check(state: dict) -> bool:
        if state.get("scope") != "short":
            return True
        owner = state.get("until_branch_merged")
        return owner == branch if owner else state.get("writer") == writer

    return check


def _capped(lines: list[str], ids: list[str]) -> list[str]:
    """Show the first lines. Name the rest, so that nothing is lost."""
    if len(lines) <= MAX_LINES:
        return lines
    rest = ids[MAX_LINES:]
    more = clean(f"- and {len(rest)} more: {', '.join(rest)}. Read one with `memory show ID`.")
    return [*lines[:MAX_LINES], more]


def _changed_elsewhere(memory: Memory, state: dict) -> list[str]:
    """Facts that another branch or auto-tidy wrote or ended after this session loaded.

    Times have one-second steps, so a record in the same second counts. `heard` stops a repeat.
    A fact from a branch that this session used is its own, also after a switch.
    """
    heard = state.setdefault("heard", [])
    writers = {*state.get("writers", []), writer_name(memory.project.root)}
    state["writers"] = sorted(writers)
    visible = _for_this_branch(memory)
    since = parse_time(state["loaded_at"])
    lines, ids = [], []
    for record in memory.records:
        when = _since(record)
        if not when or record.get("writer") in writers:
            continue
        try:
            if parse_time(when) < since:
                continue
        except ValueError:
            continue
        fact = memory.states.get(record.get("id"))
        if not fact or not visible(fact):
            continue
        label = "new" if record.get("type") == "fact" else record.get("status")
        token = f"{label}:{fact['id']}"
        if label and token not in heard:
            heard.append(token)
            lines.append(clean(f"- {label} [{fact['id']}] {load_text(fact)}"))
            ids.append(fact["id"])
    return _capped(lines, ids)


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
    visible = _for_this_branch(memory)
    rows = []
    for fact in active_states(memory):
        if fact["id"] in shown or fact.get("kind") == "rule" or not visible(fact):
            continue
        parts = score_parts(fact, moment, new, set())
        if parts["area"] or parts["mention"]:
            rows.append((-(parts["trap"] + parts["area"] + parts["recency"]), fact["id"], fact))
    rows.sort(key=lambda row: row[:2])
    facts = [row[2] for row in rows]
    state["shown"] = sorted(shown | {fact["id"] for fact in facts})
    lines = [clean(f"- [{fact['id']}] {load_text(fact)}") for fact in facts]
    return _capped(lines, [fact["id"] for fact in facts]), sorted(known | areas)


def news(memory: Memory, key: str) -> str | None:
    """What changed in the memory or in the work since this session last heard. Once each."""
    state = load_state(memory, key)
    if state is None or not state.get("loaded_at"):
        return None
    parts = []
    if state.pop("compacted", False):
        parts.append("Context was compacted. Run `memory load` to read the memory again.")
    stored = []
    elsewhere = _changed_elsewhere(memory, state)
    if elsewhere:
        stored += ["Memory changed on another branch:", *elsewhere]
    relevant, areas = _now_relevant(memory, state)
    state["areas"] = areas
    if relevant:
        stored += ["These stored facts match the files you changed:", *relevant]
    if stored:
        parts.append("\n".join([FRAME_HEADER, *stored, FRAME_FOOTER]))
    save_state(memory, key, state)
    return "\n\n".join(parts) or None


def traps_for(memory: Memory, paths: list[str], limit: int = 3) -> list[str]:
    """Stored traps that match the files about to be committed. A warning, never a refusal."""
    areas = areas_for_paths(paths, memory.config["areas"])
    if not areas:
        return []
    moment = now()
    visible = _for_this_branch(memory)
    found = []
    for fact in active_states(memory):
        if fact.get("kind") != "trap" or not visible(fact):
            continue
        parts = score_parts(fact, moment, areas, set())
        if parts["trap"]:
            found.append(
                f"memory: a stored trap matches this commit ({DATA_LABEL}): "
                f"{clean(load_text(fact))}"
            )
    return found[:limit]
