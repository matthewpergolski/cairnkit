"""Events that a session should hear about. The tool names them. The agent decides.

Nothing here writes a fact, so no text from the tool can load as memory. The state lives in the
session file (see session.py). Each event is reported once.
"""

from __future__ import annotations

import os
import re

from cairnkit import loopbreak
from cairnkit.clock import now, parse_time
from cairnkit.load import active_states, changed_paths
from cairnkit.memory import Memory
from cairnkit.paths import current_branch, run_git, writer_name
from cairnkit.secretscan import find_secrets
from cairnkit.selection import (
    DATA_LABEL,
    FRAME_FOOTER,
    FRAME_HEADER,
    areas_for_paths,
    clean,
    load_text,
    score_parts,
)
from cairnkit.session import (
    OWN_COMMIT,
    REFLOG_LIMIT,
    agent_writes,
    load_state,
    loop_nudge,
    save_state,
    tracked_files_gone,
)
from cairnkit.similar import analyze

FIX_MIN_FAILS = 2
MAX_LINES = 5
REVERT = re.compile(r"(?i)^revert(?:s|ed)?\s|^revert(?:\([^)]*\))?!?:")
REFLOG_TIME = re.compile(r"@\{(\d+)\}")
COMMAND_WIDTH = 200
ASK_TRAP = "Does a trap belong in memory?"
GONE_NAMES = 3
PROMPT_WIDTH = 120
# A correction opens a prompt. Deep in a long paste, these words belong to the paste.
PROMPT_HEAD = 300
NAMED_LIMIT = 200
QUOTED = re.compile(r"```.*?```|`[^`]*`|\"[^\"]*\"", re.DOTALL)
# A harness turn opens with a tag. A stop follow-up comes back as a prompt on some tools.
NOT_THE_OWNER = re.compile(r"^\s*<|`memory |\bmemory check\b|\bDoes a trap belong\b")
# `clean`, `clear` and `drop` also mean a tidy-up with no loss, so they must name a file.
REMOVAL = re.compile(
    r"\b(?:remove|delete|rm|get rid of|wipe|purge|prune|erase|trash|discard)\b"
    r"|\b(?:clean(?:\s+up)?|clear(?:\s+out)?|drop)\b(?=.*\b(?:files?|folders?|director(?:y|ies))\b)",
    re.IGNORECASE,
)
NEGATED = re.compile(
    r"\b(?:not|never|don't|dont|without|avoid|keep)\b(?:\s+\w+)?\s*$", re.IGNORECASE
)
CLAUSE_END = re.compile(r"(?<=[.!?:])\s+|[,;\n]|\s+(?:and|then)\s+", re.IGNORECASE)
# Words of a request that name no file, after `analyze`.
NOT_A_NAME = frozenset(
    {"all", "any", "dir", "directory", "each", "every", "file", "folder", "of", "out", "some"}
    | {"that", "them", "these", "this", "those", "unused", "up", "my", "our", "in", "from", "it"}
)
NOT_CLAUSE = r"(?<!\bif )(?<!\bwhen )(?<!\bonce )(?<!\bafter )(?<!\bbefore )(?<!\bwhether )"
CORRECTION = re.compile(
    "|".join(
        (
            rf"{NOT_CLAUSE}\byou (?:just )?(?:deleted|removed|broke|overwrote|wiped|dropped|forgot"
            r"|missed|ignored|lost|skipped)\b",
            r"\byou (?:should not|shouldn't) have\b",
            r"\bwhy did you\b",
            r"\b(?:i|we) (?:told|asked) you\b",
            r"\bi said to\b",
            r"\bi (?:did not|didn't|never) (?:ask|say|tell|want)\b",
            r"\b(?:that|this|it)(?:'s| is| was| isn't| is not)"
            r" (?:wrong|incorrect|not right|not what i)\b",
            r"\b(?:that|this|it) (?:is not|isn't) (?:right|correct|what i)\b",
            r"\bnot what i (?:asked|meant|wanted|said)\b",
            r"^\W*wrong (?:\w+)\b",
            r"\bwrong (?:file|branch|repo|folder|directory),",
            r"\bundo (?:that|this|it)\b",
            r"\bput (?:it|that|them|this) back\b",
            r"\bstop (?:doing|adding|deleting|removing|changing|ignoring)\b",
            r"\b(?:do not|don't) do that again\b",
            r"\bmy \S+(?: \S+)? (?:is|are) (?:gone|missing)\b",
            r"^\W*no[,.!:]\s+(?!thanks|problem|worries|need|rush|hurry|go ahead"
            r"|(?:that|it)(?:'s| is) (?:fine|ok|okay|good))",
            r"^\W*nope\b",
        )
    ),
    re.IGNORECASE,
)


def _quoted(command: str) -> str:
    """A command in a code span that it cannot close."""
    flat = clean(command).replace("`", "'")
    cut = "..." if len(flat) > COMMAND_WIDTH else ""
    return f"`{flat[:COMMAND_WIDTH]}{cut}`"


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
        state["told"] = [t for t in state.get("told", []) if t != _loop_token(command)]
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


def is_correction(prompt: str) -> bool:
    """True when the owner's words say that the agent got something wrong. English only."""
    if NOT_THE_OWNER.search(prompt):
        return False
    return bool(CORRECTION.search(QUOTED.sub(" ", prompt[:PROMPT_HEAD])))


def removal_words(prompt: str) -> set[str]:
    """The words of what the owner asked to remove: `remove scratch files` gives `scratch`.

    A false word would hide a real loss, and a missed word costs one question. So this reads one
    clause, and it skips a question, a refusal and a correction.
    """
    if NOT_THE_OWNER.search(prompt) or is_correction(prompt):
        return set()
    found: set[str] = set()
    for clause in CLAUSE_END.split(prompt[:PROMPT_HEAD]):
        ask = REMOVAL.search(clause)
        if ask and not clause.rstrip().endswith("?") and not NEGATED.search(clause[: ask.start()]):
            found |= analyze(clause[ask.end() :]) - NOT_A_NAME
    return found


def note_prompt(memory: Memory, key: str, prompt: str) -> None:
    """Keep what a stop needs from a prompt: a correction, and the names of files the owner used."""
    state = load_state(memory, key)
    if state is None or not prompt.strip():
        return
    named = {word.strip("`'\",:;!?()").rstrip(".") for word in prompt.split()}
    named = {word for word in named if "." in word or "/" in word}
    state["named"] = sorted({*state.get("named", []), *named})[:NAMED_LIMIT]
    state["asked"] = sorted({*state.get("asked", []), *removal_words(prompt)})[:NAMED_LIMIT]
    if is_correction(prompt):
        flat = clean(prompt)
        text = "" if find_secrets(flat, memory.env) else flat[:PROMPT_WIDTH]
        state["correction"] = {"writes": agent_writes(memory), "text": text}
    save_state(memory, key, state)


def _correction_line(memory: Memory, state: dict) -> str | None:
    """The newest correction, once. A fact written after it is the answer to the question."""
    found = state.pop("correction", None)
    if not found or agent_writes(memory) > found.get("writes", 0):
        return None
    words = _quoted(found["text"]) if found["text"] else "(text held back: it looks like a secret)"
    return f"The owner corrected you: {words}. {ASK_TRAP}"


def _named_in_a_fact(memory: Memory, state: dict, path: str) -> bool:
    name = os.path.basename(path)
    started = state.get("started_at", "")
    return any(
        name in str(record.get("text", ""))
        for record in memory.records
        if record.get("type") == "fact" and str(record.get("learned_at", "")) >= started
    )


def _gone_line(memory: Memory, state: dict) -> str | None:
    """Files that were here when the session started and that it deleted. Each is named once.

    This reads the disk and git and no hook payload, so each agent gets it, whatever deleted the
    file. A commit that came in from elsewhere does not count.
    """
    root = memory.project.root
    gone = [path for path in state.get("others", []) if not os.path.lexists(root / path)]
    if state.get("start_head"):
        gone += tracked_files_gone(root, memory.dir, state["start_head"])
    told, named = state.setdefault("told", []), set(state.get("named", []))
    asked = set(state.get("asked", []))
    fresh = []
    for path in gone:
        token = f"gone:{path}"
        if token in told:
            continue
        told.append(token)
        known = path in named or os.path.basename(path) in named or asked & analyze(path)
        if not known and not _named_in_a_fact(memory, state, path):
            fresh.append(path)
    if not fresh:
        return None
    shown = ", ".join(_quoted(path) for path in fresh[:GONE_NAMES])
    more = f" and {len(fresh) - GONE_NAMES} more" if len(fresh) > GONE_NAMES else ""
    verb = "was" if len(fresh) == 1 else "were"
    return f"{shown}{more} {verb} here when this session started and not now. {ASK_TRAP}"


def session_events(memory: Memory, key: str) -> list[str]:
    """New events that a later session may need. Each one is returned once."""
    state = load_state(memory, key)
    if state is None:
        return []
    told = state.setdefault("told", [])
    found = []
    for command, count in state.get("fixed", []):
        shown = _quoted(loopbreak.without_secret(command, memory.env))
        line = f"{shown} failed {count} times, then passed. What fixed it?"
        found.append((f"fixed:{command}", line))
    for line in _reverts(memory.project.root, state):
        found.append((f"revert:{line}", f"A revert: {line}. Why did the first attempt not hold?"))
    fresh = [(token, line) for token, line in found if token not in told]
    told.extend(token for token, _ in fresh)
    lines = [line for _, line in fresh]
    lines += [line for line in (_correction_line(memory, state), _gone_line(memory, state)) if line]
    save_state(memory, key, state)
    return lines


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
