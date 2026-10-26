"""`memory instructions`: a short block of rules for agents, and a writer for it."""

from __future__ import annotations

from pathlib import Path

from cairnkit import markers
from cairnkit.rules import DEFAULT_RULES
from cairnkit.schema import BASES, KINDS

START = "<!-- cairnkit:start -->"
END = "<!-- cairnkit:end -->"
# The markers before the rename. A block found with them is replaced by a new one.
PAIRS = ((START, END), ("<!-- project-memory:start -->", "<!-- project-memory:end -->"))

TEXT = """\
## Project memory

This project has a private memory outside the repo, linked as `memory-bank`.
A hook runs `memory load` at session start. Read its output before you work.

- **Write a fact** when you learn something a later session needs and the code,
  git and docs do not hold it: a decision and its reason, a trap, a lesson, a
  preference of the owner. Example:
  `memory add "TEXT" --kind trap --area deploy --basis seen --source commit:HASH`
  Kinds: {kinds}. Basis: {bases}.
  Source: commit:HASH, file:PATH, pr:N, session:DATE, person:ROLE.
- **Look before you add.** Run `memory search WORDS` first. If a fact already says
  it, use `--supersedes ID`. `memory add` never refuses a fact. It supersedes an exact
  repeat by itself. It writes a near repeat and flags the pair; an agent task
  (`proposals/tidy-followups.md`) lists each flagged pair.
- **Long or short.** Decisions, traps and lessons are long-term (the default).
  Working notes for this branch or task are short-term: add `--short`, or
  `--short --until-merged` to end them when the branch is merged.
- **Change a fact, do not edit it.**
  A newer fact replaces it (superseded): `memory add "..." --supersedes ID --reason "..."`.
  It stopped being true: `memory change ID --status expired --reason "..."`.
  It was never true: `memory change ID --status wrong --reason "..."`.
  A short-term note is still true later: `memory keep ID`.
- **Look before you try.** `memory search WORDS --all` shows old facts with the
  reason they ended. Use it to answer "did we try this before?".
- **Basis.** Write `seen` only for what you observed. Mark a conclusion `guess`.
- **Never store a secret** (password, key, token, private link) in a fact.
- **Never edit files in `memory-bank/` by hand**, except `notes/`. Use the
  `memory` command. Never commit `memory-bank`.
- **Before you finish**, run `memory check --strict` and fix what it reports.

### Rules

The rules live in memory, and `memory load` prints them first. They come from
rule presets (`memory preset list`) and from people. The `commits` preset holds
these rules:

{rules}
"""


def text() -> str:
    return TEXT.format(
        rules="\n".join(f"- {rule}" for rule in DEFAULT_RULES),
        kinds=", ".join(KINDS),
        bases=", ".join(BASES),
    )


def block() -> str:
    return f"{START}\n{text()}{END}\n"


def write_block(path: Path) -> str:
    """Add or replace the marked block in path. Return what happened."""
    new = block()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new)
        return "created"
    old = path.read_text(encoding="utf-8")
    found, (start_mark, end_mark) = markers.find(old, PAIRS)
    if found == "broken":
        return "broken"
    start, end = old.find(start_mark), old.find(end_mark)
    if found == "ok":
        updated = old[:start] + new + old[end + len(end_mark) :].removeprefix("\n")
        if updated == old:
            return "unchanged"
        path.write_text(updated)
        return "updated"
    sep = "" if old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
    path.write_text(old + sep + new)
    return "appended"


def replace_block(path: Path, dry_run: bool = False) -> str:
    """Replace the one marked block in place. Never append.

    Return missing (no file or no markers), broken (a lost marker or two
    blocks), unchanged or updated.
    """
    try:
        old = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "missing"
    found, (start_mark, end_mark) = markers.find(old, PAIRS)
    if found != "ok":
        return found
    start, end = old.find(start_mark), old.find(end_mark)
    updated = old[:start] + block() + old[end + len(end_mark) :].removeprefix("\n")
    if updated == old:
        return "unchanged"
    if not dry_run:
        path.write_text(updated, encoding="utf-8")
    return "updated"


def planned(path: Path) -> str:
    if not path.exists():
        return "create"
    old = path.read_text(encoding="utf-8")
    found, _ = markers.find(old, PAIRS)
    if found == "ok":
        return "unchanged" if block() in old else "update"
    return "broken" if found == "broken" else "append"


def write_instructions(project, mode: str, file: str | None, dry_run: bool) -> int:
    """Write the block. Mode `local` uses an ignored file; `shared` a tracked one."""
    from cairnkit.ignore import exclude, is_tracked

    rel = file or ("AGENTS.local.md" if mode == "local" else "AGENTS.md")
    target = project.root / rel
    if mode == "local" and is_tracked(project, rel):
        print(f"error: {rel} is tracked by git; use --write-instructions=shared for it")
        return 1
    result = planned(target) if dry_run else write_block(target)
    if result == "broken":
        print(markers.broken_message(target, "memory instructions --write-instructions"))
        return 1
    if dry_run:
        print(f"would {result} the rules block in {target}")
    else:
        print(f"{result} the rules block in {target}")
        from cairnkit.refresh import record

        record(project, None, rel)
    if mode == "local":
        for step in exclude(project, [rel], dry_run):
            print(("would " if dry_run else "") + step)
    return 0
