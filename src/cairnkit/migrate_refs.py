"""Old-layout references for `memory migrate`: rewrite the exact ones, list the rest.

The old notes were files in `memory-bank/`. They now live in
`memory-bank/notes/`. This module does three things, and none of them uses a model:

- `rewrite_text` changes `memory-bank/REL` to `memory-bank/notes/REL` when the
  old folder held `REL`. Nothing else changes.
- `judgment_items` finds the lines it must not change: instructions that name the
  old checker or the old notes folder. They go to a task for an agent.
- `render_followups` writes that task.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from cairnkit.paths import LINK_NAME

# Names in the new layout. A path that starts with one of these is not an old path.
NEW_DIRS = ("notes", "facts", "branches", "proposals")
NEW_FILES = ("config.toml", "README.md")

PATH_RE = re.compile(rf"(?<![\w-]){LINK_NAME}/([A-Za-z0-9_.\-/]*[A-Za-z0-9_/])")
OLD_DOC_RE = re.compile(rf"(?<![\w-]){LINK_NAME}(?:[-_.][\w-]+)")
CHECKER_RE = re.compile(r"check[_-]?memory", re.IGNORECASE)
CHECKER_CMD_RE = re.compile(
    r"(?:uv run(?: --no-project)? |python3? )?[^\s`'\"()]*check[_-]?memory[^\s`'\"()]*?"
    r"\.(?:py|sh|mjs|js|ts)",
    re.IGNORECASE,
)
SCRIPT_SUFFIXES = {".py", ".sh", ".mjs", ".js", ".ts"}
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".worktrees"}
MAX_BYTES = 500_000
MAX_DOCS = 200
MAX_REFS = 40
PENDING = "# Migration follow-up (pending)"
DONE = "# Migration follow-up (done)"


@dataclass
class Item:
    file: str
    line: int
    kind: str  # checker, old-path, old-doc, old-doc-file, hook
    text: str
    reason: str
    suggestion: str


def is_new_layout(rel: str) -> bool:
    return rel.split("/")[0] in NEW_DIRS or rel in NEW_FILES


def rewrite_text(text: str, exists: Callable[[str], bool]) -> tuple[str, int]:
    """Move `memory-bank/REL` to `memory-bank/notes/REL` when `exists(REL)`. Return (text, n)."""
    count = 0

    def move(match: re.Match) -> str:
        nonlocal count
        rel = match.group(1)
        if is_new_layout(rel) or not exists(rel):
            return match.group(0)
        count += 1
        return f"{LINK_NAME}/notes/{rel}"

    return PATH_RE.sub(move, text), count


def judgment_items(file: str, text: str, exists: Callable[[str], bool]) -> list[Item]:
    """Lines that name the old layout and need a person's or an agent's judgment."""
    items: list[Item] = []
    if re.search(r"memory[-_]?bank", PurePosixPath(file).name, re.IGNORECASE):
        items.append(
            Item(
                file,
                1,
                "old-doc-file",
                PurePosixPath(file).name,
                "The name says this file is about the old notes folder.",
                "Rewrite it for `memory` (`memory load`, `memory add`, notes in "
                f"{LINK_NAME}/notes/), or remove it.",
            )
        )
    for number, line in enumerate(text.splitlines(), start=1):
        reasons: list[tuple[str, str, str]] = []
        named = CHECKER_RE.search(line)
        if named:
            fixed = CHECKER_CMD_RE.sub("memory check", line)
            suggestion = (
                fixed.strip()
                if fixed != line
                else "Replace the old checker with `memory check` (and `memory load` at session "
                "start)."
            )
            reasons.append(
                (
                    "checker",
                    f"It names the old checker ({named.group(0)}). That script reads the old "
                    "layout and is now unused.",
                    suggestion,
                )
            )
        for match in PATH_RE.finditer(line):
            rel = match.group(1)
            if not is_new_layout(rel) and not exists(rel):
                reasons.append(
                    (
                        "old-path",
                        f"{LINK_NAME}/{rel} is not in the new notes.",
                        f"Find the new place (`memory search`, {LINK_NAME}/notes/), or remove it.",
                    )
                )
                break
        if OLD_DOC_RE.search(line):
            reasons.append(
                (
                    "old-doc",
                    "It names a doc or file that describes the old notes folder.",
                    "Say what the memory is now: `memory load` shows it at session start, "
                    f"`memory add` writes a fact, notes are in {LINK_NAME}/notes/. "
                    "Remove the line if it only describes the old layout.",
                )
            )
        if reasons:
            items.append(
                Item(
                    file,
                    number,
                    reasons[0][0],
                    line.strip()[:200],
                    " ".join(r[1] for r in reasons),
                    reasons[0][2],
                )
            )
    return items


def doc_files(root: Path) -> list[str]:
    """Top-level `*.md` and `docs/**/*.md`, relative to the root."""
    found = sorted(root.glob("*.md")) + sorted(root.glob("docs/**/*.md"))[:MAX_DOCS]
    return [p.relative_to(root).as_posix() for p in found if p.is_file() and not p.is_symlink()]


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))  # keeps the line endings the file had


def checker_scripts(files: Iterable[str]) -> list[str]:
    return [
        f
        for f in files
        if CHECKER_RE.search(PurePosixPath(f).name) and PurePosixPath(f).suffix in SCRIPT_SUFFIXES
    ]


def checker_references(root: Path, files: Iterable[str], scripts: list[str]) -> list[str]:
    """`file:line` for each line outside the checker scripts that names the old checker."""
    refs: list[str] = []
    for rel in files:
        if rel in scripts:
            continue
        text = read_text(root / rel)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if CHECKER_RE.search(line):
                refs.append(f"{rel}:{number}")
    return refs[:MAX_REFS]


def hook_line(root: Path, rel: str, command: str) -> int:
    text = read_text(root / rel) or ""
    needle = json.dumps(command)[1:-1]
    for number, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return number
    return 1


def grep_pattern(old_names: Iterable[str]) -> str:
    """An extended regex that finds the old names. It finds nothing when the work is done."""
    esc = lambda name: re.sub(r"([^A-Za-z0-9_/-])", r"\\\1", name)  # noqa: E731
    names = "|".join(esc(n) for n in sorted(old_names))
    parts = [f"{LINK_NAME}[-_.][[:alnum:]]", "check[_-]?memory"]
    if names:
        parts.insert(0, f"{LINK_NAME}/({names})")
    return "|".join(parts)


def render_followups(
    items: list[Item],
    scripts: list[str],
    refs: list[str],
    pending_paths: tuple[int, int],
    pattern: str,
    root: Path,
    hook_files: list[str],
    skills_line: str | None = None,
) -> str:
    """The task for an agent. `pending_paths` is (paths, files) still to rewrite by `migrate`."""
    if not items and not pending_paths[0] and not skills_line:
        return f"{DONE}\n\nNothing is left. You can delete this file.\n"
    lines = [
        PENDING,
        "",
        "This is a task for an agent. `memory migrate` moved the old notes to",
        f"`{LINK_NAME}/notes/`. The lines below still name the old layout, or they are",
        "instructions that need judgment, so `memory migrate` did not edit them.",
        "Change only the lines named here. Do not write facts for this task.",
        "",
    ]
    if pending_paths[0]:
        paths, files = pending_paths
        lines += [
            f"First run `memory migrate --fix-references --yes`. It rewrites {paths} old path(s)",
            f"in {files} file(s) by itself, and it commits nothing.",
            "",
        ]
    lines += [f"## Items ({len(items)})", ""]
    for number, item in enumerate(items, start=1):
        lines += [
            f"{number}. `{item.file}:{item.line}` ({item.kind})",
            f"   - Now: `{item.text}`",
            f"   - Why: {item.reason}",
            f"   - Suggested: {item.suggestion}",
        ]
    if scripts or refs:
        lines += ["", "## The old checker", ""]
        for script in scripts:
            lines.append(
                f"- `{script}` is not deleted by migrate. It reads the old layout and is now "
                "unused."
            )
        if refs:
            lines.append("- Still referenced at: " + ", ".join(f"`{r}`" for r in refs))
        lines.append("- Remove the script only after nothing references it, and ask first.")
    if skills_line:
        lines += [
            "",
            "## The pstack skills",
            "",
            f"- {skills_line}",
            "- Run that command. It works at user level and changes no file in the repo.",
        ]
    md = f"grep -rnE '{pattern}' --include='*.md' ./*.md"
    if (root / "docs").is_dir():
        md += " docs"
    checks = [f"This prints nothing: `{md}`"]
    if hook_files:
        files = " ".join(hook_files)
        checks.append(f"This prints nothing: `grep -nE 'check[_-]?memory' {files}`")
    checks.append("`memory check` says ok.")
    if skills_line:
        checks.append("`memory skills status` shows no tool as `not installed` or `behind`.")
    checks.append("Run `memory migrate --yes`: it marks this file done. Or delete this file.")
    lines += ["", "## Done when", ""]
    lines += [f"{number}. {check}" for number, check in enumerate(checks, start=1)]
    return "\n".join(lines) + "\n"
