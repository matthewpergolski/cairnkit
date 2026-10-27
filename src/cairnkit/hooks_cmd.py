"""`memory hooks install` and `memory hooks uninstall`."""

from __future__ import annotations

import os

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


def run_install(
    project: Project,
    agent: str,
    dry_run: bool,
    git_hook: bool,
    guard: str | None,
    flag: str | None = None,
) -> int:
    names = adapters.detect(project) if agent == "auto" else [agent]
    hooks = ["pre-commit", "post-checkout", "pre-push", "post-merge"] if git_hook else []
    hooks += ["commit-msg"] if guard == "local" else []
    broken = githook.broken_paths(project, hooks, shared=guard == "shared")
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
        steps += githook.install(
            project, "pre-commit", githook.pre_commit_body(shared=False), dry_run
        )
        steps += githook.install(
            project, "post-checkout", githook.post_checkout_body(shared=False), dry_run
        )
        steps += githook.install(project, "pre-push", githook.pre_push_body(), dry_run)
        steps += githook.install(project, "post-merge", githook.post_merge_body(), dry_run)
    if project.is_git and guard == "local":
        body = githook.guard_body(guard_patterns(project, flag))
        steps += githook.install(project, "commit-msg", body, dry_run)
    elif project.is_git and guard == "shared":
        steps += githook.install_shared(project, guard_patterns(project, flag), dry_run)
    steps += _sync_rules(project, flag, dry_run)
    if dry_run:
        print("Dry run: nothing will change.")
    else:
        refresh.record(project, flag)
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
        for hook in ("pre-commit", "post-checkout", "pre-push", "post-merge", "commit-msg"):
            steps += githook.uninstall(project, hook, dry_run)
        steps += _sync_rules(project, None, dry_run)
    for step in steps:
        plain = step.startswith(("skip", "note"))
        print(("would " if dry_run and not plain else "") + step)
    if not steps:
        print("No memory hooks found. Nothing to do.")
    return 0
