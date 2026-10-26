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
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path

from cairnkit import adapters, instruction_files, skills
from cairnkit.candidates import Candidate, Counts, scan_text
from cairnkit.check import run_check
from cairnkit.config import load_config
from cairnkit.hooks_cmd import run_install
from cairnkit.init import STATUS, plan_link, run_init
from cairnkit.migrate_refs import (
    CHECKER_RE,
    DONE,
    PENDING,
    Item,
    checker_references,
    checker_scripts,
    doc_files,
    grep_pattern,
    hook_line,
    judgment_items,
    read_text,
    render_followups,
    rewrite_text,
    write_text,
)
from cairnkit.paths import LINK_NAME, Project, resolve_memory_dir, run_git

OLD_SUFFIX = ".memory-old"
CANDIDATES_FILE = "proposals/migrate-candidates.jsonl"
TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
JUNK = {".DS_Store"}
FOLLOWUPS_FILE = "proposals/migrate-followups.md"
NEW_NAMES = ("notes", "facts", "branches", "proposals", "config.toml", "README.md")
TIERS = ("likely", "maybe", "worktree-only")


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


def copy_notes(source: Path, notes: Path, dry_run: bool) -> tuple[int, int, list[str]]:
    """Copy files into notes/ with the same paths. Never overwrite a note.

    The one exception is the empty `status.md` that `memory init` writes.
    Return (copied, same, differing relative paths).
    """
    copied = same = 0
    differing: list[str] = []
    for rel in _files(source):
        target = notes / rel
        origin = source / rel
        if not target.exists():
            copied += 1
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, target)
        elif filecmp.cmp(origin, target, shallow=False):
            same += 1
        elif rel == "status.md" and target.read_text(encoding="utf-8", errors="replace") == STATUS:
            copied += 1
            if not dry_run:
                shutil.copy2(origin, target)
        else:
            differing.append(rel)
    return copied, same, differing


def scan_folder(source: Path) -> tuple[list[Candidate], dict[str, Counts], int]:
    """Scan the text files. Return the candidates, counts by file, and files skipped."""
    found: list[Candidate] = []
    counts: dict[str, Counts] = {}
    skipped = 0
    for rel in _files(source):
        if Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            skipped += 1
            continue
        text = (source / rel).read_text(encoding="utf-8", errors="replace")
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
        "note": "Candidates only. No fact was written. Add facts with `memory add`.",
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
    for name in names:
        n = sum(c.worktree == name for c in found)
        print(f"{n} worktree-only line(s) from {name} (in the worklist, tier worktree-only)")
    long_ones = sum(c.too_long for c in found)
    if long_ones:
        print(f"{long_ones} candidate(s) are over 400 characters: split them before `memory add`.")


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


def _references(
    project: Project, source_dir: Path, fix: bool, dry_run: bool, would: str
) -> tuple[list[Item], tuple[int, int], bool]:
    """Rewrite or plan the exact old paths. Return the judgment items, what is left, changed."""
    root = project.main_root

    def exists(rel: str) -> bool:
        return (source_dir / rel.rstrip("/")).exists()

    changes: list[tuple[str, int, str]] = []
    items: list[Item] = []
    for rel in doc_files(root):
        text = read_text(root / rel)
        if text is None:
            continue
        new, count = rewrite_text(text, exists)
        if count:
            changes.append((rel, count, new))
        items += judgment_items(rel, new, exists)
    total = sum(c for _, c, _ in changes)
    if not changes:
        if fix:
            print("No old paths to rewrite.")
        return items, (0, 0), False
    print("Old paths in the top-level and docs notes:")
    for rel, count, _ in changes:
        print(f"  {rel} ({_label(project, root, rel)}): {count} path(s)")
    print(f"{total} path(s) in {len(changes)} file(s) name the old layout.")
    if not fix:
        print(
            "To rewrite them (working tree only, never committed): "
            "`memory migrate --fix-references --yes`."
        )
        return items, (total, len(changes)), False
    if dry_run:
        print("--fix-references would rewrite them in the working tree only. Nothing is committed.")
        print("Apply with: `memory migrate --fix-references --yes`.")
        return items, (0, 0), False
    for rel, _, new in changes:
        write_text(root / rel, new)
    print(
        f"Rewrote {total} path(s) in {len(changes)} file(s). Nothing is committed. "
        "Review with `git diff`:"
    )
    stat = run_git(root, "diff", "--stat", "--", *[rel for rel, _, _ in changes], timeout=15)
    print(stat or "  (the files are not tracked, so git has no diff)")
    return items, (0, 0), True


def _hooks(
    project: Project, path_flag: str | None, fix: bool, dry_run: bool
) -> tuple[list[Item], int]:
    stale = adapters.stale_hooks(project, CHECKER_RE)
    if not stale:
        return [], 0
    root = project.main_root
    print("Hooks that run the old checker:")
    items = []
    for hook in stale:
        label = "tracked by git" if _tracked(root, hook.rel) else "not tracked"
        print(f"  {hook.rel} ({label}), {hook.event}: {hook.command}")
        note = (
            " The file is tracked: change it on a branch, with the team's OK."
            if label[0] == "t"
            else ""
        )
        items.append(
            Item(
                hook.rel,
                hook_line(root, hook.rel, hook.command),
                "hook",
                f"{hook.event}: {hook.command}"[:200],
                "This hook runs the old checker, which reads the old layout." + note,
                "Make sure `memory hooks install` has run, then remove this hook handler.",
            )
        )
    code = 0
    if fix:
        print("memory hooks install adds the memory hooks next to these. It removes nothing:")
        for agent in sorted({hook.agent for hook in stale}):
            code = run_install(project, agent, dry_run, True, None, path_flag) or code
    else:
        print(
            "To add the memory hooks: `memory migrate --fix-references --yes`, "
            "or `memory hooks install`."
        )
    return items, code


def _followups(
    project: Project,
    memdir: Path,
    source_dir: Path,
    items: list[Item],
    pending: tuple[int, int],
    dry_run: bool,
) -> tuple[Path | None, int, bool]:
    """Write the agent task. Return (its path when it exists, item count, changed)."""
    root = project.main_root
    files = repo_files(project, doc_files(root))
    scripts = checker_scripts(files)
    refs = checker_references(root, files, scripts)
    if scripts or refs:
        shown = ", ".join(refs[:6]) + (" ..." if len(refs) > 6 else "")
        name = ", ".join(scripts) if scripts else "the old checker"
        print(f"The old checker ({name}) is not deleted. It is now unused.")
        if refs:
            print(f"Still referenced at: {shown}")
    names = [
        p.name for p in source_dir.iterdir() if p.name not in NEW_NAMES and p.name != ".DS_Store"
    ]
    hook_files = sorted({i.file for i in items if i.kind == "hook"})
    items = sorted(items, key=lambda i: (i.file, i.line))
    skills_line = skills.advisory() if load_config(memdir)["skills_check"] else None
    text = render_followups(
        items, scripts, refs, pending, grep_pattern(names), root, hook_files, skills_line
    )
    path = memdir / FOLLOWUPS_FILE
    old = path.read_text(encoding="utf-8") if path.is_file() else None
    if text.startswith(DONE) and not (old or "").startswith(PENDING):
        return None, 0, False
    count = len(items) + (1 if skills_line else 0)
    if old == text:
        return path, count, False
    print(f"{'would write' if dry_run else 'wrote'} the follow-up task {path}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return path, count, True


def run_migrate(
    project: Project,
    path_flag: str | None,
    from_dir: str,
    dry_run: bool = False,
    presets: list[str] | None = None,
    untrack: bool = False,
    fix_references: bool = False,
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

    if dry_run:
        print("Plan only: nothing will change without --yes.")
    print(f"Old notes: {source_dir} ({len(_files(source_dir))} file(s))")
    would = "would " if dry_run else ""
    for path, target, _ in moves:
        print(f"{would}move {path} -> {target}")
        if not dry_run:
            _move(path, target)

    if not dry_run:
        source_dir = holder  # the moved folder, or the one an earlier run moved
    code = run_init(project, path_flag, dry_run, False, presets, moved)
    if code != 0:
        print(
            f"The old notes are safe in {holder}. Fix the problem, then run "
            "`memory migrate` again.",
            file=sys.stderr,
        )
        return code

    notes = memdir / "notes"
    copied, same, differing = copy_notes(source_dir, notes, dry_run)
    print(f"{would}copy {copied} file(s) to {notes}; {same} already there")
    for rel in differing:
        print(f"note {notes / rel} differs from the old file. Left as it is.")
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

    found, counts, skipped = scan_folder(source_dir)
    asides = aside_folders(root, extras, dry_run)
    for name, (here, final) in asides.items():
        found += worktree_only(source_dir, name, here, final)
    homed = skip_homed(root, found, counts)
    _report_counts(found, counts, skipped, list(asides), homed)
    work = memdir / CANDIDATES_FILE
    text = _worklist(found, counts, homed)
    changed = bool(moves) or copied > 0
    if work.is_file():
        if work.read_text(encoding="utf-8") == text:
            print(f"worklist {work} is up to date")
        else:
            print(f"worklist {work} exists and differs. Not overwritten.")
    else:
        changed = True
        print(f"{would}write worklist {work}")
        if not dry_run:
            work.parent.mkdir(parents=True, exist_ok=True)
            work.write_text(text, encoding="utf-8")

    if os.path.normpath(from_dir) != LINK_NAME:
        print(
            f"--fix-references and the follow-up task apply only to the {LINK_NAME} folder. "
            "Skipped."
        )
        follow, follow_count, hooks_added, hook_code = None, 0, False, 0
    else:
        ref_items, pending, rewrote = _references(
            project, source_dir, fix_references, dry_run, would
        )
        changed = changed or rewrote
        hook_items, hook_code = _hooks(project, path_flag, fix_references, dry_run)
        hooks_added = bool(hook_items) and fix_references
        follow, follow_count, wrote = _followups(
            project, memdir, source_dir, ref_items + hook_items, pending, dry_run
        )
        changed = changed or wrote

    if untrack and tracked:
        changed = True
        for path, checkout in tracked:
            rel = os.path.relpath(path, checkout)
            print(f"{would}run git rm -r --cached {rel} in {checkout}")
            if not dry_run:
                run_git(checkout, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", rel)
        print("Nothing is committed. Review `git status`, then commit the removal yourself.")
    elif tracked:
        print("git still tracks the old folder. Run again with --untrack to stage its removal.")

    if dry_run:
        print()
        print("This was the plan. Nothing changed. Read it, then run `memory migrate --yes`.")
        line = skills.once_line(memdir, record=False)
        if line:
            print(line)
        return 0
    if not changed:
        print("Already migrated. Nothing to do.")
    code = run_check(project, path_flag, hint=False) or hook_code
    line = skills.once_line(memdir)
    if line:
        print(line)
    print()
    if not hooks_added:
        print("Next: `memory hooks install` if you have not run it.")
    print(f"Then add facts from {LINK_NAME}/{CANDIDATES_FILE}: `memory add ... --source file:...`.")
    print(f"The old folder is kept at {holder}. Delete it yourself when you are sure.")
    if follow and follow_count:
        print(f"Follow-up task for an agent ({follow_count} item(s)): {follow}")
        print("`memory load` shows a one-line reminder until the task is done.")
    return code
