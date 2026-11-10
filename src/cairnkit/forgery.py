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
# Words of a script that write a file. A shell step is read for its real write targets instead.
_SCRIPT_WRITES = re.compile(
    r"\b(?:write|write_text|write_bytes|open|dump|rename|replace|copy|copyfile|copytree|move"
    r"|symlink|unlink|remove|touch)\b"
)
_REDIRECT = re.compile(r"^(?:\d+|&)?>>?(?P<target>.*)$")
# A repo seldom holds a `.sessions/` folder, so a bare one is the memory folder's.
_BARE_SESSIONS = re.compile(r"^(?:\./)?\.sessions/")
# Programs whose last argument is where they write, and programs that write each file argument.
_TO_LAST = frozenset({"cp", "mv", "install", "ln", "rsync"})
_TO_EACH = frozenset({"tee", "touch", "truncate", "rm", "unlink"})
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
    for part, _ in _parts(command):
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
    """Paths in the memory folder's facts/ or .sessions/, named through the folder or its link."""
    names = sorted({re.escape(memory_dir), re.escape(PurePath(memory_dir).name), re.escape(link)})
    return re.compile(rf"(?:{'|'.join(names)})/+(?:facts|\.sessions)(?:/|$)")


def _write_targets(words: list[str]) -> list[str]:
    """The files a plain shell step writes: redirect targets, the destination of cp/mv/tee and the
    like, `dd of=`, and the files of `sed -i` or `perl -i`. `2>/dev/null` and `2>&1` write none."""
    targets: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(words):
        word = words[index]
        redirect = _REDIRECT.match(word)
        if redirect and not word.startswith("<"):
            target = redirect["target"] or (words[index + 1] if index + 1 < len(words) else "")
            index += 1 if redirect["target"] else 2
            if target and not target.startswith("&") and target != "/dev/null":
                targets.append(target)
            continue
        rest.append(word)
        index += 1
    if not rest:
        return targets
    head, args = PurePath(rest[0]).name, [w for w in rest[1:] if not w.startswith("-")]
    if head in _TO_LAST and args:
        targets.append(args[-1])
    elif head in _TO_EACH:
        targets += args
    elif head == "dd":
        targets += [w[3:] for w in rest[1:] if w.startswith("of=")]
    elif head in ("sed", "perl") and any(w.startswith("-i") for w in rest[1:]):
        targets += args[1:]
    return targets


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
    # A script fed to python another way (`python - <<EOF`, a file) that imports the internals.
    runs_python = any(_PYTHON.fullmatch(PurePath(words[0]).name) for words, _, _ in steps)
    if runs_python and "import" in command and _INTERNALS.search(command):
        return REFUSED.format(what="call cairnkit in a way that skips its checks")
    paths = [_memory_paths(str(folder), link) for folder in memory_dirs]
    names = {link, *(PurePath(str(f)).name for f in memory_dirs), *(str(f) for f in memory_dirs)}
    targets: list[str] = []
    inside = False  # after `cd` into the memory folder, a relative target is in it
    for words, _, kind in steps:
        if kind != "plain":
            continue
        if words[0] == "cd" and len(words) > 1:
            inside = any(words[1].rstrip("/").endswith(name) for name in names)
            continue
        for target in _write_targets(words):
            relative = "" if target.startswith("/") else re.sub(r"^(?:\./)+", "", target)
            if _BARE_SESSIONS.match(target) or (
                inside and relative.startswith(("facts/", "facts"))
            ):
                target = f"{link}/{relative}"
            targets.append(target)
    if any(path.search(target) for path in paths for target in targets):
        return REFUSED.format(what="write into the memory folder's facts/ or .sessions/")
    script_text = scripts + (command if runs_python else "")
    if any(path.search(script_text) for path in paths) and _SCRIPT_WRITES.search(script_text):
        return REFUSED.format(what="write into the memory folder's facts/ or .sessions/")
    return None
