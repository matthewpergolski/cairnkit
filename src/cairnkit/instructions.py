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


def write_block(path: Path, *, prefix: str = "") -> str:
    """Add or replace the marked block in path. Return what happened."""
    new = block()
    if not path.exists():
        path.resolve().parent.mkdir(parents=True, exist_ok=True)  # a dangling link: its target
        path.write_text(prefix + new)
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


def remove_block(path: Path, dry_run: bool = False) -> str:
    """Remove the one marked block. Hand-written text outside it stays.

    Return missing, broken, unchanged or removed.
    """
    try:
        old = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "missing"
    found, (start_mark, end_mark) = markers.find(old, PAIRS)
    if found != "ok":
        return found
    start, end = old.find(start_mark), old.find(end_mark)
    updated = old[:start] + old[end + len(end_mark) :].removeprefix("\n")
    if updated == old:
        return "unchanged"
    if not dry_run:
        path.write_text(updated, encoding="utf-8")
    return "removed"


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


def migrate_shared_blocks(
    project, dry_run: bool = False, checkouts: list[Path] | None = None
) -> tuple[list[str], list[Path]]:
    """Move cairnkit blocks out of CLAUDE.md / AGENTS.md. Leave hand-written text.

    Return (step messages, broken paths).
    """
    from cairnkit import rules_target

    steps: list[str] = []
    broken: list[Path] = []
    for checkout in checkouts if checkouts is not None else [project.root]:
        for name in rules_target.SHARED:
            path = checkout / name
            if not path.is_file() or rules_target.is_loop(path):
                continue
            result = remove_block(path, dry_run=dry_run)
            if result == "broken":
                broken.append(path)
            elif result == "removed":
                steps.append(f"remove the rules block from {path}")
    return steps, broken


def write_instructions(project, mode: str, file: str | None, dry_run: bool) -> int:
    """Write the block to an untracked local file. Never write a tracked rules file."""
    from cairnkit import harness_local, rules_target
    from cairnkit.ignore import exclude, is_tracked

    said = "would " if dry_run else ""
    root = project.root
    if mode == "shared":
        print(
            "error: shared rules blocks are no longer written into tracked CLAUDE.md or "
            "AGENTS.md. Use --write-instructions (local). It writes CLAUDE.local.md and "
            "moves any cairnkit block out of those tracked files."
        )
        return 1
    looped = rules_target.loops(root, file)
    for name in looped:
        print(f"error: {name} is a symlink loop. Remove or fix the link. Nothing was written.")
    if looped:
        return 1
    here = rules_target.present(root)
    found = ", ".join(here) if here else "none of " + ", ".join(rules_target.LOOKED_AT)
    if rules_target.same_file(root):
        found += " (CLAUDE.md and AGENTS.md are the same file)"
    print("found: " + found)

    migrate_steps, broken = migrate_shared_blocks(project, dry_run)
    for step in migrate_steps:
        print(said + step)
    for path in broken:
        print(markers.broken_message(path, "memory instructions --write-instructions"))
    if broken:
        return 1

    if file:
        rel, why = file, f"--instructions-file: the block goes to {file}."
    else:
        rel, why = (
            rules_target.LOCAL,
            f"Local mode: the block goes to {rules_target.LOCAL}, kept out of git.",
        )
    print(why)
    target = root / rel
    if is_tracked(project, rel):
        print(f"error: {rel} is tracked by git; pick an untracked file with --instructions-file")
        return 1
    real = rules_target.link_target(root, rel)
    if real not in (None, rel) and is_tracked(project, real):
        print(
            f"error: {rel} is a link to {real}, which is tracked by git. "
            "Nothing was written. Remove the link, or pick another untracked file."
        )
        return 1
    result = planned(target) if dry_run else write_block(target)
    if result == "broken":
        print(markers.broken_message(target, "memory instructions --write-instructions"))
        return 1
    print(f"{said}{result} the rules block in {target}")
    if rules_target.needs_import(root, rel):
        if not dry_run:
            rules_target.add_import(target)
        print(
            f"{said}add {rules_target.IMPORT} at the top of {rel}. Claude Code skips AGENTS.md "
            f"when {rel} exists, so the import makes it load both."
        )
    written = [rel]
    if not file:
        for harness in harness_local.TARGETS:
            path = root / harness.rel
            if is_tracked(project, harness.rel):
                print(f"note: {harness.rel} is tracked; skipped the {harness.harness} local copy")
                continue
            real_h = rules_target.link_target(root, harness.rel)
            if real_h not in (None, harness.rel) and is_tracked(project, real_h):
                print(
                    f"note: {harness.rel} links to tracked {real_h}; "
                    f"skipped the {harness.harness} local copy"
                )
                continue
            if dry_run:
                action = planned(path)
                print(f"{said}{action} the rules block in {path} ({harness.harness})")
            else:
                action = write_block(path, prefix=harness.prefix if not path.exists() else "")
                if action == "broken":
                    print(markers.broken_message(path, "memory instructions --write-instructions"))
                    return 1
                print(f"{said}{action} the rules block in {path} ({harness.harness})")
            written.append(harness.rel)
    if not dry_run:
        from cairnkit.refresh import record

        for name in written:
            record(project, None, name)
    exclude_lines = list(dict.fromkeys(written))
    for step in exclude(project, exclude_lines, dry_run):
        print(said + step)
    old = root / rules_target.OLD_LOCAL
    if rel != rules_target.OLD_LOCAL and rules_target.holds_block(old):
        print(
            f"note: {rules_target.OLD_LOCAL} holds an old rules block. The local block now goes to "
            f"{rules_target.LOCAL}. You can remove {rules_target.OLD_LOCAL} by hand. "
            "`memory init --refresh` still updates it until then."
        )
    return 0
