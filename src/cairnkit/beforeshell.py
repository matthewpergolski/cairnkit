"""Before a shell command runs: a stored fact that gives a longer form of the same command.

The data shape. A command line splits into steps at `;`, `&`, `|` and newlines outside quotes. Each
step is its own settings (the `NAME=value` words in front) and its core (the other words, with
output redirects removed). A core of one plain word, such as `make`, is no step. A fact matches a
step when its text holds the whole core behind a prefix that the step lacks: a setting such as
`REPORT_LOCALE=C`, or a wrapper such as `uv run`. That is how to run this command, which the agent
is about to run in the short form.

Precision matters more than recall here, because a hook that speaks on unrelated commands teaches
an agent to skip it. So a fact that only names the same file does not match. Each fact speaks at
most once in a session, and the text is the masked text that the load shows.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shlex
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from cairnkit import plainfile
from cairnkit.clock import now
from cairnkit.memory import Memory
from cairnkit.paths import merged_checker
from cairnkit.selection import DATA_LABEL, clean, render
from cairnkit.state import effective_status
from cairnkit.store import locked

SETTING = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\S*")
REDIRECT = re.compile(r"&?\d*(?:>>?|<)(&\d+|&-)?")
REDIRECT_JOINED = re.compile(r"&?\d*(?:>>?|<)\S+")
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(['\"]?)([A-Za-z0-9_]+)\1")
WRAPPERS = (
    ("env",),
    ("sudo",),
    ("uv", "run"),
    ("poetry", "run"),
    ("pdm", "run"),
    ("pipenv", "run"),
    ("hatch", "run"),
    ("bundle", "exec"),
    ("npx",),
    ("pnpm", "exec"),
    ("bunx",),
)
OPENERS = "`'\"("
# After the core: the text ends, a space, a closing mark, or a stop that ends a sentence.
AFTER_CORE = r"(?=$|[\s`'\"),;:]|[.!?](?:\s|$))"
TOLD_LOCK = ".before-shell.lock"
# A step that moves to a folder or reports a status, around the work: `cd x;`, `echo "exit=$?"`.
NOT_WORK = frozenset({"cd", "pushd", "popd", "echo", "printf"})
# A step that reads the output of the step before it through a pipe and only shows a part of it:
# `pytest -q 2>&1 | tail -5`. A retry often shows another part, so it is no work either.
FILTERS = frozenset({"tail", "head", "grep", "wc", "tee", "sort", "uniq", "less", "cat"})


@dataclass(frozen=True)
class Step:
    settings: frozenset[str]
    core: str
    piped: bool = False  # it reads the output of the step before it (`a | b`)


@dataclass(frozen=True)
class Hit:
    fact_id: str
    form: str  # the longer form, as the fact writes it


def _words(step: str) -> list[str]:
    try:
        return shlex.split(step)
    except ValueError:
        return step.split()


def _core_words(words: list[str]) -> list[str]:
    kept, skip = [], False
    for word in words:
        if skip:
            skip = False
        elif REDIRECT.fullmatch(word):
            skip = not word.rstrip("0123456789-").endswith("&")
        elif not REDIRECT_JOINED.fullmatch(word):
            kept.append(word)
    return kept


def _redirect_amp(command: str, index: int) -> bool:
    """The `&` of `2>&1` or `&>`, which is part of a redirect, not the end of a step."""
    return command[index - 1 : index] in ("<", ">") or command[index + 1 : index + 2] == ">"


def _past_heredocs(command: str, index: int, ends: list[str]) -> int | None:
    """The index after the end lines of these heredocs, from the line at `index`, or None."""
    for end in ends:
        while True:
            stop = command.find("\n", index)
            line = command[index:] if stop < 0 else command[index:stop]
            index = len(command) if stop < 0 else stop + 1
            if line.strip() == end:
                break
            if stop < 0:
                return None
    return index


def _parts(command: str) -> list[tuple[str, bool]]:
    """The command split at each `;`, `&`, `|` and newline outside quotes and heredoc bodies.

    Each part comes with True when a pipe (`|` or `|&`, not `||`) leads into it. Empty if a quote
    or a heredoc is open. A split inside quotes would make a step of a grep pattern such as
    `'check\\.py|manage\\.py'`, and a heredoc body is text, not commands.
    """
    parts, start, quote, index, ends, piped = [], 0, "", 0, [], False
    while index < len(command):
        char = command[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        heredoc = None if quote else HEREDOC.match(command, index)
        if heredoc:
            ends.append(heredoc.group(2))
            index = heredoc.end()
            continue
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char in ";|\n" or (char == "&" and not _redirect_amp(command, index)):
            parts.append((command[start:index], piped))
            pair = command[index : index + 2]
            piped = char == "|" and pair != "||"
            index += 1 if pair in ("||", "|&", "&&") else 0
            start = index + 1
            if char == "\n" and ends:
                after = _past_heredocs(command, start, ends)
                if after is None:
                    return []
                start, ends = after, []
                index = after
                continue
        index += 1
    return [] if quote or ends else [*parts, (command[start:], piped)]


def _plain_core(core: list[str]) -> bool:
    """One word alone, such as `make`, is part of too many commands. A path is not."""
    return len(core) > 1 or any(mark in core[0] for mark in "./")


def all_steps(command: str) -> list[Step]:
    """Each step of the command, one plain word too."""
    found = []
    for part, piped in _parts(command):
        words = _words(part.strip())
        settings = []
        while words and SETTING.fullmatch(words[0]):
            settings.append(words.pop(0))
        core = _core_words(words)
        if core:
            found.append(Step(frozenset(settings), " ".join(core), piped))
    return found


def steps(command: str) -> list[Step]:
    return [step for step in all_steps(command) if _plain_core(step.core.split())]


def _work(command: str) -> list[Step]:
    def is_work(step: Step) -> bool:
        head = step.core.split()[0]
        return head not in NOT_WORK and not (step.piped and head in FILTERS)

    return [step for step in all_steps(command) if is_work(step)]


def added_in_front(failed: str, passed: str) -> tuple[str, str] | None:
    """What `passed` puts in front of a step of `failed`, and that step's core, or None.

    Only a retry counts: `passed` does the same work steps in the same order, and puts a setting
    or a wrapper in front of one, which is how to run it. A `cd`, an `echo` and a filter after a
    pipe (`| tail -5`) are no work. A pass that does other work holds no fix of the failure, also
    when one failed step is in it.
    """
    before, after = _work(failed), _work(passed)
    if len(before) != len(after):
        return None
    found = None
    for old, step in zip(before, after, strict=True):
        leads = [" ".join(w) for w in WRAPPERS if step.core == f"{' '.join(w)} {old.core}"]
        if step.core == old.core:
            fix = " ".join(sorted(step.settings - old.settings))
        elif leads and step.settings >= old.settings:
            fix = leads[0]
        else:
            return None
        if fix and found is None:
            found = (fix, old.core)
    return found


def _wrapper_at_end(words: list[str]) -> tuple[str, ...] | None:
    for wrapper in WRAPPERS:
        tail = words[-len(wrapper) :]
        if len(tail) == len(wrapper) and (tail[0].lstrip(OPENERS), *tail[1:]) == wrapper:
            return wrapper
    return None


def _prefix(before: list[str]) -> list[str]:
    """The settings and wrappers at the end of `before`, in order. A code span opens no further."""
    words, prefix = list(before), []
    while words:
        opens = words[-1][:1] in OPENERS
        last = words[-1].lstrip(OPENERS)
        wrapper = None if SETTING.fullmatch(last) else _wrapper_at_end(words)
        if wrapper:
            opens = words[-len(wrapper)][:1] in OPENERS
            prefix[:0] = wrapper
            del words[-len(wrapper) :]
        elif SETTING.fullmatch(last):
            prefix.insert(0, last)
            words.pop()
        else:
            break
        if opens:
            break
    return prefix


def longer_form(text: str, step: Step) -> str | None:
    """The form in `text` of the same core behind a prefix that the step lacks, or None."""
    flat = " ".join(text.split())
    if step.core not in flat:
        return None
    for found in re.finditer(rf"(?<=\s){re.escape(step.core)}{AFTER_CORE}", flat):
        prefix = _prefix(flat[: found.start()].split())
        added = [word for word in prefix if word not in step.settings]
        if added:
            return " ".join([*prefix, step.core])
    return None


def hits(command: str, facts: Iterable[dict]) -> list[Hit]:
    parsed = steps(command)
    found = []
    for fact in facts:
        text = str(fact.get("text") or "")
        for step in parsed:
            form = longer_form(text, step)
            if form:
                found.append(Hit(str(fact["id"]), form))
                break
    return found


def _active(memory: Memory) -> list[dict]:
    moment = now()
    return [s for s in memory.states.values() if effective_status(s, moment)[0] == "active"]


def _told_path(memory: Memory, key: str, kind: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()[:24]
    return memory.dir / ".sessions" / f"{kind}-{digest}.json"


def take_once(memory: Memory, key: str, kind: str, tokens: list[str]) -> list[str]:
    """The tokens of this kind that this key (a session, or one agent in it) has not had. Marks
    them as had.

    A file of its own for each kind, read and written under a lock. Helpers share their parent's
    session key, so a hook of one can save the session state from a read before this write.
    """
    path = _told_path(memory, key, kind)
    with locked(memory.dir / ".sessions" / TOLD_LOCK, root=memory.dir):
        try:
            told = set(json.loads(plainfile.read_text(path, encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            told = set()
        fresh = [token for token in dict.fromkeys(tokens) if token not in told]
        if fresh:
            # The time budget can end a write. A rename keeps the old record whole, and the session
            # prune removes a `.state-*.tmp` that a kill left.
            folder = plainfile.inside(memory.dir, path.parent)
            fd, tmp = tempfile.mkstemp(dir=folder, prefix=".state-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(sorted(told | set(fresh))))
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
    return fresh


def message(memory: Memory, key: str, command: str) -> str | None:
    """What the agent hears before the command runs, once for each fact, or None."""
    found = hits(command, _active(memory))
    if not found:
        return None
    is_merged = merged_checker(memory.project.root)
    found = [
        hit
        for hit in found
        if effective_status(memory.states[hit.fact_id], now(), is_merged)[0] == "active"
    ]
    fresh = set(take_once(memory, key, "before", [hit.fact_id for hit in found])) if found else ()
    found = [hit for hit in found if hit.fact_id in fresh]
    if not found:
        return None
    lines = [f"{render(memory.states[hit.fact_id])}" for hit in found]
    forms = ", ".join(f"`{clean(hit.form).replace('`', '')}`" for hit in found)
    return (
        f"memory: this call did not run. A stored fact is about this command ({DATA_LABEL}):\n"
        + "\n".join(lines)
        + f"\nIt gives {forms}. Run the command again with that in mind. A fact stops one call "
        "in a session."
    )
