"""Before a shell command of an agent: a command that would forge the owner's evidence.

A process of the same user can write any file of the memory, so code inside `memory` cannot stop
it. The agent tool's shell is the boundary that cairnkit can see: its before-shell hook refuses a
command that would

- run a cairnkit hook by hand (`memory hook prompt`, `python -m cairnkit hook`), which is how a
  fake owner prompt or a fake answer to an agent question gets in;
- change or remove an agent marker of the environment (see MARKERS) and run `memory`, which is how
  an agent's `told` claim would bind as the owner's own words at a terminal;
- write into the memory folder's `facts/` or `.sessions/` (a redirect, `tee`, `cp`, `mv`,
  `sed -i`, a script that writes a file).

The data shape. A command line splits into steps (beforeshell._parts). The words of a step lose
their settings (`NAME=value`) and wrappers (`env`, `sudo`, `uv run`, ...); what is left is the
program and its arguments. `bash -c` and `python -c` scripts are read as well. A heredoc body is
not a step, so a script fed by a heredoc is caught only by the plain-text checks at the end.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable
from pathlib import PurePath

from cairnkit.beforeshell import SETTING, _parts
from cairnkit.owner_evidence import SESSION_ENV
from cairnkit.skills import AGENT_SHELL_MARKERS, MARKERS

# Each variable that tells cairnkit an agent runs it, or which session it is in.
AGENT_ENV = frozenset(
    {*AGENT_SHELL_MARKERS, *SESSION_ENV, *(name for names in MARKERS.values() for name in names)}
)
PROGRAMS = frozenset({"memory", "cairnkit"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
PLAIN_WRAPPERS = frozenset({"sudo", "exec", "command", "nohup", "time", "nice", "builtin"})
# Options of `uv run`, `uvx` and `env` that take a value.
VALUE_OPTIONS = frozenset(
    {"--with", "--from", "--python", "-p", "--project", "--directory", "--package", "-u", "--unset",
     "-C", "--chdir", "-S", "--split-string", "--env-file"}
)  # fmt: skip
_PYTHON = re.compile(r"python[\d.]*")
_MODULE = re.compile(r"cairnkit(?:\.cli|\.__main__)?")
_INTERNALS = re.compile(r"\b(?:owner_evidence|note_prompt|note_answer|hookrun)\b")
_ENVIRON = re.compile(r"\benviron\b|\bputenv\b|\bunsetenv\b")
_WRITE_WORDS = re.compile(
    r"\b(?:tee|cp|mv|install|ln|rsync|dd|truncate|touch|write|write_text|write_bytes|open|dump"
    r"|rename|replace|copy|copyfile|move|symlink)\b|>|\bsed\b[^|;&]*\s-i|\bperl\b[^|;&]*\s-i"
)
REFUSED = (
    "memory: this call did not run. It would {what}. Only the owner's own terminal and the agent "
    "tool's hooks may do that, because it decides what counts as the owner's words. Run `memory` "
    "as it is, in this shell, with no change to its environment. If the owner wants a rule to "
    "bind, they say it in the chat, or they run `memory add` in their own terminal."
)


def _words(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _unwrapped(words: list[str]) -> tuple[list[str], set[str]]:
    """The program and its arguments, and the variables that the settings and wrappers change.

    `*` stands for all of them (`env -i`).
    """
    changed: set[str] = set()
    words = list(words)
    while words:
        head = PurePath(words[0]).name
        if SETTING.fullmatch(words[0]):
            changed.add(words.pop(0).split("=", 1)[0])
        elif head in PLAIN_WRAPPERS:
            words.pop(0)
        elif head == "env":
            words.pop(0)
            while words and (words[0].startswith("-") or SETTING.fullmatch(words[0])):
                word = words.pop(0)
                if word in ("-i", "--ignore-environment", "-"):
                    changed.add("*")
                elif word in ("-u", "--unset") and words:
                    changed.add(words.pop(0))
                elif word.startswith("--unset="):
                    changed.add(word.split("=", 1)[1])
                elif SETTING.fullmatch(word):
                    changed.add(word.split("=", 1)[0])
        elif (head in ("uv", "pipx") and words[1:2] == ["run"]) or head == "uvx":
            del words[: 1 if head == "uvx" else 2]
            while words and words[0].startswith("-"):
                option = words.pop(0)
                if option in VALUE_OPTIONS and words and "=" not in option:
                    words.pop(0)
        else:
            break
    return words, changed


def _runs_memory(words: list[str]) -> str | None:
    """The cairnkit subcommand that the words run, `""` for none named, or None for no cairnkit."""
    if not words:
        return None
    head = PurePath(words[0]).name
    if head in PROGRAMS:
        return words[1] if len(words) > 1 else ""
    if _PYTHON.fullmatch(head) and len(words) > 2 and words[1] == "-m":
        return (words[3] if len(words) > 3 else "") if _MODULE.fullmatch(words[2]) else None
    return None


def _script(words: list[str]) -> tuple[str, str] | None:
    """("shell" or "python", the script) for `bash -c SCRIPT` and `python -c SCRIPT`."""
    if len(words) < 3 or "-c" not in words[1:-1]:
        return None
    head = PurePath(words[0]).name
    script = words[words.index("-c", 1) + 1]
    if head in SHELLS:
        return "shell", script
    if _PYTHON.fullmatch(head):
        return "python", script
    return None


def _steps(command: str, depth: int = 0) -> Iterable[tuple[list[str], set[str], str]]:
    """(program words, changed variables, kind) for each step, `bash -c` scripts too."""
    for part in _parts(command):
        words, changed = _unwrapped(_words(part.strip()))
        script = _script(words)
        if script and script[0] == "shell" and depth < 3:
            for inner, more, kind in _steps(script[1], depth + 1):
                yield inner, changed | more, kind
        elif script:
            yield words, changed, "python"
        elif words:
            yield words, changed, "plain"


def _memory_paths(memory_dir: str, link: str) -> re.Pattern:
    names = sorted({re.escape(memory_dir), re.escape(PurePath(memory_dir).name), re.escape(link)})
    return re.compile(
        rf"(?:{'|'.join(names)})/+(?:facts|\.sessions)(?:/|\b)"
        r"|(?:^|[\s'\"=:(])\.?/?\.sessions/|(?:^|[\s'\"=:(])\.?/?facts/[^\s'\"]*\.jsonl"
    )


def refusal(command: str, memory_dirs: Iterable[str], link: str = "memory-bank") -> str | None:
    """Why the agent may not run this command, or None. See the module text."""
    steps = list(_steps(command))
    changed = set().union(*(step[1] for step in steps)) if steps else set()
    for words, _, _kind in steps:
        if words[0] in ("unset", "export", "declare", "typeset"):
            changed |= {word.split("=", 1)[0] for word in words[1:] if not word.startswith("-")}
    runs = [_runs_memory(words) for words, _, kind in steps if kind == "plain"]
    if "hook" in runs:
        return REFUSED.format(what="run a cairnkit hook by hand")
    marker_change = "*" in changed or bool(changed & AGENT_ENV)
    in_python = [words for words, _, kind in steps if kind == "python"]
    scripts = " ".join(words[words.index("-c", 1) + 1] for words in in_python)
    if any(run is not None for run in runs) and marker_change:
        return REFUSED.format(what="run `memory` with an agent marker changed or removed")
    if "cairnkit" in scripts and (
        _INTERNALS.search(scripts) or _ENVIRON.search(scripts) or "hook" in scripts
    ):
        return REFUSED.format(what="call cairnkit from a script in a way that skips its checks")
    if "cairnkit" in command and (
        _INTERNALS.search(command)
        or (_ENVIRON.search(command) and any(name in command for name in AGENT_ENV))
    ):
        return REFUSED.format(what="call cairnkit in a way that skips its checks")
    paths = [_memory_paths(str(folder), link) for folder in memory_dirs]
    if any(path.search(command) for path in paths) and _WRITE_WORDS.search(command):
        return REFUSED.format(what="write into the memory folder's facts/ or .sessions/")
    return None
