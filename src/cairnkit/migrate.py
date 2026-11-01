"""`memory migrate`: fold a prose memory folder into a project memory.

Steps, all deterministic, no model, no fact written:

1. Move the old folder out of the repo to `<repo>.memory-old`. Nothing is deleted.
2. Run the normal `memory init`.
3. Copy the old files into the new `notes/`, with the same relative paths.
4. Write a worklist of candidate facts, with the file and line of each.
5. With `--untrack`, take the old folder out of the git index. Nothing is committed.
6. Run `memory check`.

Without `--yes` it only prints the plan. A rerun after a failure finishes the
job. The old files are always in the `.memory-old` folder, or in the move that
was not done yet.

A rerun after those steps does none of them. It reads the agent task again, and
it removes the task when nothing is left. That is the end of the migration.
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

from cairnkit import adapters, githook, hooks_cmd, instruction_files, skills
from cairnkit.candidates import Candidate, Counts, mark_repeats, scan_text
from cairnkit.check import run_check
from cairnkit.envsecrets import EnvValues, read_env_values
from cairnkit.hooks_cmd import run_install
from cairnkit.init import STATUS, plan_link, run_init
from cairnkit.memory import Memory
from cairnkit.migrate_refs import (
    CANDIDATES,
    CHECKER_RE,
    OLD_COPIES,
    OLD_SUFFIX,
    TASK,
    TEXT_SUFFIXES,
    Item,
    checker_references,
    checker_scripts,
    doc_files,
    dropped_checks,
    hook_line,
    hook_reads_old_notes,
    is_stub,
    judgment_items,
    named_old_files,
    old_copy_items,
    outside_layout,
    read_text,
    render_followups,
    rewrite_text,
    rewritten_docs,
    stray_files,
    stub_text,
)
from cairnkit.paths import LINK_NAME, Project, resolve_memory_dir, run_git
from cairnkit.schema import MAX_TEXT
from cairnkit.secretscan import find_secrets

JUNK = {".DS_Store"}
TIERS = ("likely", "maybe", "worktree-only", "repeat")


def _entries(folder: Path) -> list[Path]:
    """Every file under a folder (a link counts), sorted. Junk files are left out."""
    return sorted(p for p in folder.rglob("*") if not p.is_dir() and p.name not in JUNK)


def _has_content(folder: Path) -> bool:
    return folder.is_dir() and not folder.is_symlink() and bool(_entries(folder))


def _files(folder: Path) -> list[str]:
    """Relative paths of the regular files, as posix text."""
    return [p.relative_to(folder).as_posix() for p in _entries(folder) if not p.is_symlink()]


def _fail(message: str) -> int:
    print(f"error: {message}\nNothing changed.", file=sys.stderr)
    return 1


def _move(source: Path, target: Path) -> None:
    try:
        os.rename(source, target)
    except OSError:
        shutil.move(str(source), str(target))


def _tracked(checkout: Path, rel: str) -> bool:
    return bool(run_git(checkout, "ls-files", "--", rel))


def _label(project: Project, root: Path, rel: str) -> str:
    """Say if git tracks a file, and if it already has changes (the diff then shows them too)."""
    if not project.is_git or not _tracked(root, rel):
        return "not tracked"
    return (
        "tracked by git, already modified"
        if run_git(root, "status", "--porcelain", "--", rel)
        else "tracked by git"
    )


def _differing(folder: Path, reference: Path) -> int:
    """Count the files in `folder` that are not in `reference`, or that differ from it."""
    count = 0
    for rel in _files(folder):
        other = reference / rel
        if not other.is_file() or not filecmp.cmp(folder / rel, other, shallow=False):
            count += 1
    return count


def note_layout(source: Path) -> tuple[dict[str, str], list[str]]:
    """Map each note's path to its old file, and list the old files that lost to another.

    An old folder can hold `notes/REL` from an earlier move. `notes/REL` stays `notes/REL`,
    and it wins over an old `REL`, because that is the file the new layout reads.
    """
    layout: dict[str, str] = {}
    losers: list[str] = []
    for rel in sorted(_files(source), key=lambda r: not r.startswith("notes/")):
        note = rel.removeprefix("notes/")
        if note not in layout:
            layout[note] = rel
        elif not filecmp.cmp(source / rel, source / layout[note], shallow=False):
            losers.append(rel)
    return dict(sorted(layout.items())), losers


def _is_template(note: Path) -> bool:
    return note.name == "status.md" and (read_text(note) or "") == STATUS


def copy_notes(
    source: Path, notes: Path, layout: dict[str, str], dry_run: bool
) -> tuple[int, int, list[str]]:
    """Copy files into notes/. Never overwrite a note, except the empty `status.md` of init.

    Return (copied, same, the note paths that differ from their old file).
    """
    copied = same = 0
    differing: list[str] = []
    for rel, old_rel in layout.items():
        target = notes / rel
        origin = source / old_rel
        if target.exists() and filecmp.cmp(origin, target, shallow=False):
            same += 1
        elif target.exists() and not _is_template(target):
            differing.append(rel)
        else:
            copied += 1
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, target)
    return copied, same, differing


def _keep_old_copy(memdir: Path, rel: str, origin: Path, dry_run: bool) -> None:
    """Keep a copy that lost out of `notes/`, so that nothing looks active and nothing is lost."""
    place = memdir / OLD_COPIES / rel
    number = 1
    while place.exists():
        if filecmp.cmp(origin, place, shallow=False):
            return
        number += 1
        place = memdir / OLD_COPIES / f"{rel}.{number}"
    print(f"{'would keep' if dry_run else 'keep'} the other copy of {rel} at {place}")
    if not dry_run:
        place.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, place)


def _remove(path: Path, memdir: Path) -> None:
    """Remove a file, and each parent folder that it leaves empty, up to the memory folder."""
    path.unlink(missing_ok=True)
    for folder in path.parents:
        if folder == memdir or any(folder.iterdir()):
            return
        folder.rmdir()


def _settle_strays(memdir: Path, dry_run: bool) -> None:
    """Text outside the new layout goes into notes/, or beside it when a note differs."""
    would = "would " if dry_run else ""
    for rel in stray_files(memdir):
        path, note = memdir / rel, memdir / "notes" / rel
        if not note.exists() or _is_template(note):
            print(f"{would}move {path} -> {note}")
            if not dry_run:
                note.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, note)
                _remove(path, memdir)
            continue
        if filecmp.cmp(path, note, shallow=False):
            print(f"{would}remove {path}: {note} has the same text")
        else:
            _keep_old_copy(memdir, rel, path, dry_run)
        if not dry_run:
            _remove(path, memdir)


def _sync_stubs(memdir: Path, named: set[str], dry_run: bool) -> None:
    """A pointer at each old path that a doc names, because an agent that follows it lands here."""
    would = "would " if dry_run else ""
    for path in outside_layout(memdir):
        if is_stub(path) and path.relative_to(memdir).as_posix() not in named:
            print(f"{would}remove the pointer {path}")
            if not dry_run:
                _remove(path, memdir)
    for rel in sorted(named):
        path = memdir / rel
        if not path.exists():
            print(f"{would}leave a pointer to the note at {path}")
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(stub_text(rel), encoding="utf-8")


def scan_folder(
    source: Path, layout: dict[str, str]
) -> tuple[list[Candidate], dict[str, Counts], int]:
    """Scan the text files. Return the candidates, counts by file, and files skipped."""
    found: list[Candidate] = []
    counts: dict[str, Counts] = {}
    skipped = 0
    for rel, old_rel in layout.items():
        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            skipped += 1
            continue
        text = (source / old_rel).read_text(encoding="utf-8", errors="replace")
        items, count = scan_text(rel, text)
        found += items
        counts[rel] = count
    return found, counts, skipped


def _norm(text: str) -> str:
    return " ".join(text.split())


def skip_homed(root: Path, found: list[Candidate], counts: dict[str, Counts]) -> int:
    """Drop the candidates that an instruction file already holds. Return how many."""
    homes = instruction_files.items(root)
    if not homes:
        return 0
    kept = []
    for cand in found:
        if not instruction_files.home(homes, cand.text):
            kept.append(cand)
        elif not cand.worktree:
            counts[cand.file].candidates -= 1
            counts[cand.file].instructions += 1
    skipped = len(found) - len(kept)
    found[:] = kept
    return skipped


def drop_secrets(found: list[Candidate], counts: dict[str, Counts], known: EnvValues) -> list[str]:
    """Take out the candidates that hold a secret. Return where each one was, not its text."""
    kept, held = [], []
    for cand in found:
        if find_secrets(cand.text, known):
            held.append(f"{cand.file}:{cand.line}")
            if cand.file in counts:
                counts[cand.file].candidates -= 1
        else:
            kept.append(cand)
    found[:] = kept
    return held


def worktree_only(main: Path, name: str, folder: Path, final: Path) -> list[Candidate]:
    """Candidates in a worktree's own old notes that the main notes do not have.

    `folder` is where the files are now. `final` is where they stay, and the
    source of each candidate points there. A file the main notes lack counts
    in full. A file that differs counts only for its lines that are new.
    """
    found: list[Candidate] = []
    for rel in _files(folder):
        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        mine = folder / rel
        theirs = main / rel
        if theirs.is_file() and filecmp.cmp(mine, theirs, shallow=False):
            continue
        known: set[str] = set()
        if theirs.is_file():
            known = {
                _norm(c.text)
                for c in scan_text(rel, theirs.read_text(encoding="utf-8", errors="replace"))[0]
            }
        for cand in scan_text(rel, mine.read_text(encoding="utf-8", errors="replace"))[0]:
            if _norm(cand.text) not in known:
                cand.worktree, cand.origin = name, str(final / rel)
                found.append(cand)
    return found


def aside_folders(root: Path, extras: list, dry_run: bool) -> dict[str, tuple[Path, Path]]:
    """Name -> (where the files are now, where they stay) for each worktree's old notes.

    Folders that an earlier run moved are found by their name, so a rerun sees them.
    """
    prefix = f"{root.name}{OLD_SUFFIX}."
    found = {
        p.name.removeprefix(prefix): (p, p)
        for p in sorted(root.parent.iterdir())
        if p.is_dir() and p.name.startswith(prefix)
    }
    for path, target, checkout in extras:
        found[checkout.name] = (path if dry_run else target, target)
    return found


def _worklist(found: list[Candidate], counts: dict[str, Counts], homed: int) -> str:
    total = Counts()
    for count in counts.values():
        total.add(count)
    summary = {
        "type": "summary",
        "note": (
            "Candidates only. No fact was written. Add facts with `memory add`. "
            "A rule that the owner stated needs `--kind rule --basis told`, or it loads as data."
        ),
        "candidates": len(found),
        "tiers": {tier: sum(c.tier == tier for c in found) for tier in TIERS},
        "worktree_only": dict(Counter(c.worktree for c in found if c.worktree)),
        "hints": dict(Counter(c.hint for c in found if c.hint)),
        "in_instruction_files": homed,
        "lines": total.lines,
        "files": {rel: vars(count) for rel, count in counts.items()},
    }
    rows = [json.dumps(summary, ensure_ascii=False)]
    for number, cand in enumerate(found, start=1):
        row = {
            "type": "candidate",
            "id": f"c{number:04d}",
            "file": cand.file,
            "line": cand.line,
            "heading": cand.heading,
            "text": cand.text,
            "tier": cand.tier,
            "from_worktree": cand.worktree,
            "suggested_kind": cand.kind,
            "happened_at": cand.happened_at,
            "hint": cand.hint,
            "held_by": cand.held_by,
            "repeat_of": cand.repeat_of,
            "too_long": cand.too_long,
            "source": (
                f"file:{cand.origin}:{cand.line}"
                if cand.origin
                else f"file:{LINK_NAME}/notes/{cand.file}:{cand.line}"
            ),
        }
        rows.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(rows) + "\n"


def _report_counts(
    found: list[Candidate], counts: dict[str, Counts], skipped: int, names: list[str], homed: int
) -> None:
    total = Counts()
    print("Candidate facts (lines in, lines out):")
    for rel, count in counts.items():
        total.add(count)
        print(
            f"  {rel}: {count.lines} lines = {count.candidates} candidate, "
            f"{count.continuation} continued, {count.headings} heading, {count.code} code, "
            f"{count.table} table, {count.other} other"
            + (f", {count.instructions} in an instruction file" if count.instructions else "")
        )
    extra = f"; {skipped} file(s) that are not text were copied, not read" if skipped else ""
    tiers = {tier: sum(c.tier == tier for c in found) for tier in TIERS}
    main_count = tiers["likely"] + tiers["maybe"]
    print(
        f"{main_count} candidate(s) from {total.lines} line(s) in {len(counts)} text file(s)"
        f"{extra}. No fact was written."
    )
    print(
        f"{tiers['likely']} likely (decision, trap, lesson, event, brief lines) and "
        f"{tiers['maybe']} maybe (the rest; most stay notes)."
    )
    if homed:
        print(
            f"{homed} candidate(s) skipped: an instruction file already holds them "
            f"({', '.join(instruction_files.FILES)})."
        )
    if tiers["repeat"]:
        print(
            f"{tiers['repeat']} repeat(s) say what another line or a stored fact says "
            "(tier repeat, with `repeat_of`). Add only the first."
        )
    for name in names:
        n = sum(c.worktree == name for c in found)
        print(f"{n} worktree-only line(s) from {name} (in the worklist, tier worktree-only)")
    long_ones = sum(c.too_long for c in found)
    if long_ones:
        print(
            f"{long_ones} candidate(s) are over {MAX_TEXT} characters: "
            "split them before `memory add`."
        )


def repo_files(project: Project, docs: list[str]) -> list[str]:
    """Tracked files (or every file outside git) plus the doc files. Only files that exist."""
    root = project.main_root
    if project.is_git:
        listed = (run_git(root, "ls-files", timeout=15) or "").splitlines()
    else:
        skip = {".git", "node_modules", ".venv", "__pycache__", ".worktrees"}
        listed = [
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and not skip & set(p.relative_to(root).parts)
        ]
    files = {f for f in listed if (root / f).is_file() and not (root / f).is_symlink()}
    return sorted(files | set(docs))


def _references(project: Project, memdir: Path, source_dir: Path) -> tuple[list[Item], set[str]]:
    """Lines in the docs that name the old layout, and the old files they name.

    The agent decides each line. The tool edits no doc.
    """
    root = project.root
    places = (memdir / "notes", source_dir, source_dir / "notes")

    def exists(rel: str) -> bool:
        return any((place / rel.rstrip("/")).exists() for place in places)

    def is_note(rel: str) -> bool:
        return any((place / rel).is_file() for place in places)

    items: list[Item] = []
    named: set[str] = set()
    docs = doc_files(root)
    rewritten = rewritten_docs(root, docs)
    for rel in docs:
        text = read_text(root / rel)
        if text is None:
            continue
        named |= named_old_files(text, is_note)
        new, _count = rewrite_text(text, exists)
        found = judgment_items(rel, new, exists, rewritten)
        lines = text.splitlines()
        for item in found:
            if item.kind != "old-doc-file":
                item.text = lines[item.line - 1].strip()[:200]
        items += found
        for number, (before, after) in enumerate(
            zip(text.splitlines(), new.splitlines(), strict=False), start=1
        ):
            if before != after:
                items.append(
                    Item(
                        rel,
                        number,
                        "old path",
                        before.strip()[:200],
                        "This line names the old layout. The tool changes no tracked file.",
                        after.strip()[:200],
                    )
                )
    return items, named


def _hooks(project: Project) -> list[Item]:
    """Old hooks in settings files: the checker, and any other that reads the old notes."""
    root = project.root

    def is_old(command: str) -> bool:
        return bool(CHECKER_RE.search(command) or hook_reads_old_notes(root, command))

    items = []
    for hook in adapters.stale_hooks(project, is_old):
        why = (
            "This hook runs the old checker, which reads the old layout."
            if CHECKER_RE.search(hook.command)
            else f"{hook_reads_old_notes(root, hook.command)} It runs at each {hook.event}, and "
            "`memory load` now brings the memory."
        )
        note = " The tool changes no tracked file, so this edit is yours." if hook.tracked else ""
        items.append(
            Item(
                hook.rel,
                hook_line(root, hook.rel, hook.command),
                "hook",
                f"{hook.event}: {hook.command}"[:200],
                why + note,
                "Remove this hook handler. The memory hooks are already installed next to it.",
            )
        )
    return items


def _old_checker(project: Project) -> tuple[list[str], list[str]]:
    """The old checker scripts, and the `file:line` of each line that still names one."""
    root = project.root
    files = repo_files(project, doc_files(root))
    scripts = checker_scripts(files)
    return scripts, checker_references(root, files, scripts)


def _drops(project: Project, source: Path) -> list[str]:
    """Each check that the old tooling made, in the repo and in the old folder."""
    scripts = {rel: project.root / rel for rel in _old_checker(project)[0]}
    scripts |= {rel: source / rel for rel in checker_scripts(_files(source))}
    return dropped_checks(scripts)


def _write_task(
    memdir: Path, project: Project, source: Path, items: list[Item], dry_run: bool
) -> None:
    """Write the agent task, or remove it when nothing is open. The same input writes the same."""
    path = memdir / TASK
    if not items:
        if not dry_run:
            path.unlink(missing_ok=True)
        return
    scripts, refs = _old_checker(project)
    ordered = sorted(items, key=lambda i: (i.file, i.line))
    text = render_followups(ordered, scripts, refs, _drops(project, source))
    if not dry_run and (not path.is_file() or path.read_text(encoding="utf-8") != text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _say_where(project: Project, dry_run: bool) -> None:
    if dry_run:
        print("Plan only: nothing will change without --yes.")
    print(f"It acts on the main checkout {project.main_root}.")
    if project.root != project.main_root:
        print(
            f"You ran it from the worktree {project.root}. The old notes and links are handled "
            "from the main checkout. The docs for the agent task are read from this worktree."
        )


def _say_install(project: Project, would: str) -> None:
    """Name what the install step reaches, in the plan as well as in the run."""
    if not hooks_cmd.INSTALL_ON_INIT:
        return
    names = [name for name in adapters.detect(project) if name != "generic"]
    if names:
        places = ", ".join(str(checkout) for checkout in project.checkouts)
        print(
            f"{would}connect the agent tools ({', '.join(names)}) in each checkout: {places}. "
            "Each file it writes there is untracked."
        )
    folder = githook.hooks_dir(project) if project.is_git else None
    if folder:
        print(
            f"{would}add the git hooks pre-commit, post-checkout, pre-push and post-merge to "
            f"{folder}, which every checkout runs. They are not shared. "
            "It also adds commit-msg when a rule forbids AI attribution."
        )


def _close(project: Project, path_flag: str | None, memdir: Path, source: Path, dry: bool) -> int:
    """A rerun after the steps are done. It reads the task again and does nothing else."""
    _settle_strays(memdir, dry)
    references, named = _references(project, memdir, source)
    _sync_stubs(memdir, named, dry)
    items = old_copy_items(memdir)
    if (memdir / TASK).is_file():
        items += references + _hooks(project)
    _write_task(memdir, project, source, items, dry)
    code = 0 if dry else run_check(project, path_flag)
    if items:
        print(f"Migration not finished: {len(items)} item(s) left in {memdir / TASK}.")
        print("Do them, then run `memory migrate --yes` again. That task says how it ends.")
    else:
        print("Migration finished. Nothing to do.")
    return code


def run_migrate(
    project: Project,
    path_flag: str | None,
    from_dir: str,
    dry_run: bool = False,
    presets: list[str] | None = None,
    untrack: bool = False,
) -> int:
    root = project.main_root
    memdir, _ = resolve_memory_dir(project, path_flag)
    src = Path(os.path.normpath(root / from_dir))
    holder = root.parent / f"{root.name}{OLD_SUFFIX}"
    if root not in src.parents:
        return _fail(f"{src} is not a folder inside the project at {root}")
    if memdir == src or src in memdir.parents:
        return _fail(f"the memory folder {memdir} is inside the old folder {src}")

    real = _has_content(src)
    resume = not real and _has_content(holder)
    if not real and not resume:
        if src.is_symlink() and src.resolve() == memdir.resolve():
            if (memdir / TASK).is_file() or (memdir / OLD_COPIES).is_dir() or stray_files(memdir):
                _say_where(project, dry_run)
                return _close(project, path_flag, memdir, memdir / "notes", dry_run)
            print(f"{src} is already a link to {memdir}. Nothing to migrate.")
            return 0
        if src.is_symlink():
            print(
                f"error: {src} is a link to {src.resolve()}, not a folder with notes. "
                "Nothing changed. Point --from at the real folder.",
                file=sys.stderr,
            )
        else:
            print(f"error: nothing to migrate: no files in {src}.", file=sys.stderr)
        return 1
    if real and holder.exists():
        return _fail(f"{holder} exists. Move it away, then run `memory migrate` again")
    source_dir = src if real else holder

    # (folder, where it goes, its checkout). The main folder goes first.
    main_move = [(src, holder, root)] if real else []
    extras = []
    for checkout in project.checkouts:
        link = checkout / LINK_NAME
        if checkout != root and _has_content(link):
            aside = root.parent / f"{root.name}{OLD_SUFFIX}.{checkout.name}"
            if aside.exists():
                return _fail(f"{aside} exists (the old notes of the checkout {checkout})")
            extras.append((link, aside, checkout))
    moves = main_move + extras
    moved = frozenset(m[0] for m in moves)

    problems = [p for c in project.checkouts for p in [plan_link(c, memdir, moved)[1]] if p]
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        print(
            "Nothing changed. Use --from for the folder that holds the old notes.",
            file=sys.stderr,
        )
        return 1

    tracked = [
        (path, checkout)
        for path, _, checkout in moves
        if project.is_git and _tracked(checkout, os.path.relpath(path, checkout))
    ]
    if resume and project.is_git and _tracked(root, os.path.relpath(src, root)):
        tracked.append((src, root))
    if tracked and real and not untrack:
        names = ", ".join(os.path.relpath(p, c) for p, c in tracked)
        return _fail(
            f"git tracks files in {names}. Moving them would show as deleted files. "
            "Add --untrack: it takes them out of the index and commits nothing"
        )

    _say_where(project, dry_run)
    work = memdir / CANDIDATES
    if not moves and not tracked and work.is_file():
        return _close(project, path_flag, memdir, source_dir, dry_run)

    print(f"Old notes: {source_dir} ({len(_files(source_dir))} file(s))")
    would = "would " if dry_run else ""
    for path, target, _ in moves:
        print(f"{would}move {path} -> {target}")
        if not dry_run:
            _move(path, target)

    if not dry_run:
        source_dir = holder  # the moved folder, or the one an earlier run moved
    code = run_init(project, path_flag, dry_run, presets, moved)
    if code != 0:
        print(
            f"The old notes are safe in {holder}. Fix the problem, then run "
            "`memory migrate` again.",
            file=sys.stderr,
        )
        return code

    notes = memdir / "notes"
    layout, losers = note_layout(source_dir)
    copied, same, differing = copy_notes(source_dir, notes, layout, dry_run)
    print(f"{would}copy {copied} file(s) to {notes}; {same} already there")
    for rel in differing:
        print(f"note {notes / rel} differs from the old file. Left as it is.")
        _keep_old_copy(memdir, rel, source_dir / layout[rel], dry_run)
    for old_rel in losers:
        _keep_old_copy(memdir, old_rel.removeprefix("notes/"), source_dir / old_rel, dry_run)
    links = [p for p in _entries(source_dir) if p.is_symlink()]
    if links:
        print(f"{len(links)} link(s) in the old folder were not copied. They stay in {source_dir}.")
    for path, target, checkout in extras:
        count = _differing(path if dry_run else target, source_dir)
        print(
            f"checkout {checkout} has its own old notes: {count} file(s) differ from the main "
            f"copy. They {'go' if dry_run else 'are'} at {target}, not merged. "
            "Their new lines are in the worklist."
        )

    found, counts, skipped = scan_folder(source_dir, layout)
    asides = aside_folders(root, extras, dry_run)
    for name, (here, final) in asides.items():
        found += worktree_only(source_dir, name, here, final)
    homed = skip_homed(root, found, counts)
    held = drop_secrets(found, counts, read_env_values(project))
    if held:
        print(
            f"{len(held)} candidate(s) hold a secret and stay out of the worklist: "
            f"{', '.join(held)}. Remove these lines from the notes."
        )
    stored = {}
    if not dry_run and (memdir / "facts").is_dir():
        states = Memory.open(project, path_flag).states.values()
        stored = {x["id"]: str(x["text"]) for x in states if x.get("status") == "active"}
    mark_repeats(found, stored)
    _report_counts(found, counts, skipped, list(asides), homed)
    # The task goes first: a worklist on disk means that this run reached the task.
    _settle_strays(memdir, dry_run)
    items = old_copy_items(memdir)
    if os.path.normpath(from_dir) != LINK_NAME:
        print(f"The references to the old folder apply only to {LINK_NAME}. Skipped.")
    else:
        scripts, refs = _old_checker(project)
        if scripts or refs:
            name = ", ".join(scripts) if scripts else "the old checker"
            shown = ", ".join(refs[:6]) + (" ..." if len(refs) > 6 else "")
            print(f"The old checker ({name}) is not deleted. It reads the old layout.")
            print("When it and `memory check` disagree, believe `memory check`.")
            if refs:
                print(f"Still run or named at: {shown}")
        drops = _drops(project, source_dir)
        if drops:
            print("What the old tooling checked. This list prints once. Tell the developer:")
            for drop in drops:
                print(f"  {drop}")
        references, named = _references(project, memdir, source_dir)
        _sync_stubs(memdir, named, dry_run)
        items += references + _hooks(project)
    if items:
        print(f"{would}write the follow-up task {memdir / TASK}")
    _write_task(memdir, project, source_dir, items, dry_run)

    text = _worklist(found, counts, homed)
    if work.is_file():
        if work.read_text(encoding="utf-8") == text:
            print(f"worklist {work} is up to date")
        else:
            print(f"worklist {work} exists and differs. Not overwritten.")
    else:
        print(f"{would}write worklist {work}")
        if not dry_run:
            work.parent.mkdir(parents=True, exist_ok=True)
            work.write_text(text, encoding="utf-8")

    if untrack and tracked:
        for path, checkout in tracked:
            rel = os.path.relpath(path, checkout)
            print(f"{would}run git rm -r --cached {rel} in {checkout}")
            if not dry_run:
                run_git(checkout, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", rel)
        print("Nothing is committed. Review `git status`, then commit the removal yourself.")
    elif tracked:
        print("git still tracks the old folder. Run again with --untrack to stage its removal.")

    if dry_run:
        _say_install(project, "would ")
        print()
        print("This was the plan. Nothing changed. Read it, then run `memory migrate --yes`.")
        line = skills.once_line(memdir, record=False)
        if line:
            print(line)
        return 0
    code = run_check(project, path_flag)
    line = skills.once_line(memdir)
    if line:
        print(line)
    print()
    if hooks_cmd.INSTALL_ON_INIT:
        _say_install(project, "")
        code = code or run_install(project, "auto", False, True, None, path_flag, quiet=True)
    print(f"Optional: add facts from {LINK_NAME}/{CANDIDATES}: `memory add ... --source file:...`.")
    print("A rule that the owner stated needs `--kind rule --basis told`, or it loads as data.")
    print(f"The old folder is kept at {holder}. Delete it yourself when you are sure.")
    if items:
        print(f"Follow-up task for an agent ({len(items)} item(s)): {memdir / TASK}")
        print("`memory load` shows a one-line reminder until the task is done.")
    return code
