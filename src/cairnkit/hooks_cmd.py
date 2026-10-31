"""`memory hooks install` and `memory hooks uninstall`."""

from __future__ import annotations

import os
import re

from cairnkit import adapters, githook, markers, refresh, rules
from cairnkit.init import can_link, ensure_all_linked, is_linked
from cairnkit.memory import Memory, MemoryMissing
from cairnkit.paths import LINK_NAME, Project, resolve_memory_dir


def guard_patterns(project: Project, flag: str | None) -> list[str]:
    try:
        return Memory.open(project, flag).config["guard_patterns"]
    except MemoryMissing:
        return list(githook.DEFAULT_GUARD_PATTERNS)


def _sync_rules(project: Project, flag: str | None, dry_run: bool) -> list[str]:
    """Keep the default rule's enforced_by true to the installed commit-msg guard."""
    if not project.is_git or dry_run:
        return []
    try:
        memory = Memory.open(project, flag)
    except MemoryMissing:
        return []
    return rules.sync_guard(memory, githook.guard_installed(project))


# Tests turn this off, so that a test of something else does not read the real machine's tools.
INSTALL_ON_INIT = True
ATTRIBUTION = re.compile(r"(?i)attribution|co-?author|generated[- ]with")


def _has_attribution_rule(project: Project, flag: str | None) -> bool:
    """A rule against AI attribution can have a check that fails, so it gets one."""
    try:
        memory = Memory.open(project, flag)
    except MemoryMissing:
        return False
    return any(
        s.get("kind") == "rule" and s.get("status") == "active" and ATTRIBUTION.search(s["text"])
        for s in memory.states.values()
    )


def _print_summary(
    project: Project, names: list[str], guard: str | None, git_hook: bool, steps: list[str]
) -> None:
    """Two or three lines. `--verbose` or `memory hooks install` prints each step."""
    agents = [name for name in names if name != "generic"]
    print(f"Agents connected: {', '.join(agents)}." if agents else "No agent tool found here.")
    if project.is_git and git_hook:
        extra = ", and a commit-message check" if guard else ""
        print(f"Git hooks installed in .git/hooks{extra}. They are not shared.")
    for step in steps:
        if step.startswith(("skip", "note")):
            print(step)
    if "codex" in names:
        print("Codex: approve the hooks once with /hooks, because Codex asks for trust itself.")
    if "generic" in names:
        print("For any other agent, run: memory hooks install --agent generic")


def run_install(
    project: Project,
    agent: str,
    dry_run: bool,
    git_hook: bool,
    guard: str | None,
    flag: str | None = None,
    quiet: bool = False,
) -> int:
    names = adapters.detect(project) if agent == "auto" else [agent]
    guard = guard or ("local" if git_hook and _has_attribution_rule(project, flag) else None)
    hooks = ["pre-commit", "post-checkout", "pre-push", "post-merge"] if git_hook else []
    hooks += ["commit-msg"] if guard == "local" else []
    broken = githook.broken_paths(project, hooks)
    if broken:
        for path in broken:
            print(markers.broken_message(path, "memory hooks install"))
        return 1
    steps: list[str] = []
    memdir, _ = resolve_memory_dir(project, flag)
    # Link every checkout that can be linked before writing agent config into it.
    if not dry_run:
        steps += ensure_all_linked(project, flag)
    else:
        for checkout in project.checkouts:
            if can_link(project, checkout, memdir):
                target = os.path.relpath(memdir, checkout)
                steps.append(f"link {checkout / LINK_NAME} -> {target}")
    has_memory = (memdir / "facts").is_dir()
    if has_memory:
        # Real install: only linked checkouts. Dry-run: already linked or healable.
        targets = [
            c
            for c in project.checkouts
            if is_linked(c, memdir) or (dry_run and can_link(project, c, memdir))
        ]
        if not dry_run:
            for checkout in project.checkouts:
                if checkout not in targets:
                    steps.append(
                        f"skip {checkout}: not linked to {memdir}; "
                        f"run `memory init --path {memdir}` from there first"
                    )
    else:
        # No project memory yet: never put stop-hook config into an unlinked worktree.
        targets = [project.main_root]
    try:
        for name in names:
            if name != "generic":
                steps += adapters.apply(
                    project, name, install=True, dry_run=dry_run, checkouts=targets
                )
    except adapters.BadConfig as exc:
        print(f"error: {exc}")
        return 1
    if project.is_git and git_hook:
        steps += githook.install(project, "pre-commit", githook.pre_commit_body(), dry_run)
        steps += githook.install(project, "post-checkout", githook.post_checkout_body(), dry_run)
        steps += githook.install(project, "pre-push", githook.pre_push_body(), dry_run)
        steps += githook.install(project, "post-merge", githook.post_merge_body(), dry_run)
        steps += githook.uninstall(project, "post-commit", dry_run)  # 0.3.1 mined commits here
    if project.is_git and guard == "local":
        body = githook.guard_body(guard_patterns(project, flag))
        steps += githook.install(project, "commit-msg", body, dry_run)
    steps += _sync_rules(project, flag, dry_run)
    if dry_run:
        print("Dry run: nothing will change.")
    else:
        refresh.record(project, flag)
    if quiet:
        _print_summary(project, names, guard, git_hook, steps)
        return 0
    for step in steps:
        plain = step.startswith(("skip", "note"))
        print(("would " if dry_run and not plain else "") + step)
    print(f"Agents: {', '.join(names)}")
    for name in names:
        if name == "generic":
            print(adapters.generic_help())
        if name in adapters.EXPERIMENTAL:
            print(f"Note: the {name} adapter is experimental. Check it once in the tool.")
        if name == "codex":
            print("Codex runs project hooks only in a trusted project. Review them in /hooks.")
    if not steps:
        print("Already installed. Nothing to do.")
    return 0


def run_uninstall(project: Project, dry_run: bool) -> int:
    steps: list[str] = []
    try:
        for name in adapters.ADAPTERS:
            steps += adapters.apply(project, name, install=False, dry_run=dry_run)
    except adapters.BadConfig as exc:
        print(f"error: {exc}")
        return 1
    if project.is_git:
        for hook in (
            "pre-commit",
            "post-checkout",
            "pre-push",
            "post-merge",
            "post-commit",
            "commit-msg",
        ):
            steps += githook.uninstall(project, hook, dry_run)
        steps += _sync_rules(project, None, dry_run)
    for step in steps:
        plain = step.startswith(("skip", "note"))
        print(("would " if dry_run and not plain else "") + step)
    if not steps:
        print("No memory hooks found. Nothing to do.")
    return 0
