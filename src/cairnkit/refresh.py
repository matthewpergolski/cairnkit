"""The tool version that last wrote a repo's files, and `memory init --refresh`.

memory writes some files into a repo: the rules block, the agent hooks and the
git hooks. It records its version in the memory folder when it writes them.
`memory init --refresh` rewrites the files that hold memory's text, in place.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

from cairnkit import __version__, adapters, githook, instructions, markers, rules_target
from cairnkit.clock import now, stamp
from cairnkit.ignore import exclude
from cairnkit.paths import Project, resolve_memory_dir
from cairnkit.skills import is_behind

STAMP = "tool-version.json"
# Untracked block homes only. Tracked CLAUDE.md / AGENTS.md are migrated out, not refreshed.
BLOCK_FILES = (
    "AGENTS.local.md",
    "CLAUDE.local.md",
    ".cursor/rules/cairnkit.mdc",
    ".pi/APPEND_SYSTEM.md",
)
COMMAND = "memory init --refresh"


def tool_version() -> str:
    return __version__


def _memdir(project: Project, flag: str | None) -> Path | None:
    memdir, _ = resolve_memory_dir(project, flag)
    return memdir if (memdir / "facts").is_dir() else None


def read_stamp(memdir: Path) -> dict:
    try:
        data = json.loads((memdir / STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(project: Project, flag: str | None, block_file: str | None = None) -> None:
    """Record this tool version as the one that wrote the repo files. Never raises."""
    with contextlib.suppress(Exception):
        memdir = _memdir(project, flag)
        if memdir is None:
            return
        old = read_stamp(memdir)
        blocks = set(old.get("blocks") or [])
        if block_file:
            blocks.add(block_file)
        if old.get("version") == tool_version() and old.get("blocks") == sorted(blocks):
            return  # nothing new: a second run changes nothing
        data = {"version": tool_version(), "at": stamp(now()), "blocks": sorted(blocks)}
        (memdir / STAMP).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _holds(path: Path, *marks: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(mark in text for mark in marks)


def _has_block(path: Path) -> bool:
    """True when a git hook holds a start or an end marker, new or old."""
    return _holds(path, *(mark for pair in githook.PAIRS for mark in pair))


def _block_paths(project: Project, memdir: Path) -> list[Path]:
    # Include legacy CLAUDE.md / AGENTS.md so wrote_files still sees old installs.
    rels = sorted(
        set(BLOCK_FILES) | {"CLAUDE.md", "AGENTS.md"} | set(read_stamp(memdir).get("blocks") or [])
    )
    return [checkout / rel for checkout in project.checkouts for rel in rels]


def _agents(project: Project) -> dict[str, list[Path]]:
    """For each agent, the checkouts whose hook config already holds memory's hooks."""
    found = {}
    for name, adapter in adapters.ADAPTERS.items():
        holders = [c for c in project.checkouts if _holds(c / adapter.rel, *adapters.MARKS)]
        if holders:
            found[name] = holders
    return found


def _post_merge_lacks_docs_check(project: Project) -> bool:
    """A local post-merge cairnkit block with no docs-check stanza."""
    folder = githook.hooks_dir(project) if project.is_git else None
    if folder is None or githook._inside_worktree(project, folder):
        return False
    path = folder / "post-merge"
    if not _has_block(path):
        return False
    return not _holds(path, githook.DOCS_CHECK_MARK) or not _holds(path, "docs --check")


def _local_hooks(project: Project) -> list[str]:
    folder = githook.hooks_dir(project) if project.is_git else None
    if folder is None or githook._inside_worktree(project, folder):
        return []
    names = (
        "pre-commit",
        "post-checkout",
        "pre-push",
        "post-merge",
        "post-commit",
        "commit-msg",
    )
    return [h for h in names if _has_block(folder / h)]


def wrote_files(project: Project, memdir: Path) -> bool:
    return bool(
        any(_holds(p, *(s for s, _ in instructions.PAIRS)) for p in _block_paths(project, memdir))
        or _agents(project)
        or _local_hooks(project)
    )


def repo_line(project: Project, flag: str | None) -> str | None:
    """One line when repo files are older, or post-merge lacks the docs check. Never raises."""
    try:
        memdir = _memdir(project, flag)
        if memdir is None:
            return None
        version = read_stamp(memdir).get("version")
        stale_hook = _post_merge_lacks_docs_check(project)
        if version:
            if not is_behind(version, tool_version()) and not stale_hook:
                return None
        elif not wrote_files(project, memdir) and not stale_hook:
            return None
        writer = f"memory {version}" if version else "an older memory"
        return (
            f"memory: this repo's hooks and rules block come from {writer}. This is memory "
            f"{tool_version()}. Run `{COMMAND}` now. It rewrites them in place."
        )
    except Exception:
        return None


def _ensure_local_block(project: Project, dry_run: bool) -> list[str]:
    """A block that stays in a tracked file still gets its current copy in the local file."""
    path = project.root / rules_target.LOCAL
    if path.exists() and instructions.START in path.read_text(encoding="utf-8"):
        return []
    if not dry_run:
        instructions.write_block(path)
        exclude(project, [rules_target.LOCAL])
    return [f"write the rules block to {path}"]


def run_refresh(project: Project, flag: str | None, dry_run: bool) -> int:
    from cairnkit.hooks_cmd import guard_patterns

    memdir = _memdir(project, flag)
    if memdir is None:
        print("error: there is no memory here. Run `memory init` first.", file=sys.stderr)
        return 1
    steps: list[str] = []
    broken: list[Path] = []
    migrate_steps, migrate_broken = instructions.migrate_shared_blocks(
        project, dry_run, checkouts=project.checkouts
    )
    steps += migrate_steps
    broken += migrate_broken
    if any(step.startswith("note: tracked") for step in migrate_steps):
        steps += _ensure_local_block(project, dry_run)
    shared_names = {"CLAUDE.md", "AGENTS.md"}
    for path in _block_paths(project, memdir):
        if path.name in shared_names:
            continue  # migrated above; never refresh a tracked shared file in place
        result = instructions.replace_block(path, dry_run)
        if result == "updated":
            steps.append(f"update the rules block in {path}")
        elif result == "broken":
            broken.append(path)
    try:
        for name, holders in _agents(project).items():
            steps += adapters.apply(project, name, install=True, dry_run=dry_run, checkouts=holders)
    except adapters.BadConfig as exc:
        print(f"error: {exc}")
        return 1
    bodies = {
        "pre-commit": githook.pre_commit_body(),
        "post-checkout": githook.post_checkout_body(),
        "pre-push": githook.pre_push_body(),
        "post-merge": githook.post_merge_body(),
    }
    hooks = _local_hooks(project)
    broken += githook.broken_paths(project, hooks)
    for hook in hooks:
        if githook.is_broken(githook.hooks_dir(project) / hook):
            continue
        if hook == "post-commit":  # 0.3.1 mined commits here. Nothing runs there now.
            steps += githook.uninstall(project, hook, dry_run)
            continue
        body = bodies.get(hook) or githook.guard_body(guard_patterns(project, flag))
        steps += githook.install(project, hook, body, dry_run)
    if dry_run:
        print("Dry run: nothing will change.")
    for step in steps:
        plain = step.startswith(("skip", "note"))
        print(("would " if dry_run and not plain else "") + step)
    for path in broken:
        print(markers.broken_message(path, COMMAND))
    if broken:
        return 1
    if not dry_run:
        record(project, flag)
    if not steps:
        print("The repo files are current. Nothing to do.")
    return 0
