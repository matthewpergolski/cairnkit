"""Keep local files out of git with .git/info/exclude (shared by all worktrees)."""

from __future__ import annotations

from pathlib import Path

from cairnkit.paths import Project, enclosing_trees, run_git, tree_env

HEADER = "# Private project memory (a link to a folder outside the repo)"


def missing_lines(path: Path, lines: list[str]) -> list[str]:
    have = set(path.read_text().splitlines()) if path.is_file() else set()
    return [line for line in lines if line not in have]


def append_lines(path: Path, lines: list[str], header: str = HEADER) -> None:
    """Add lines under one header. Older versions wrote the header again with each new line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text().splitlines() if path.is_file() else []
    first = old.index(header) if header in old else len(old)
    kept = old[: first + 1] + [line for line in old[first + 1 :] if line != header]
    head = [] if header in old else [header]
    path.write_text("\n".join([*kept, *head, *lines]) + "\n")


def exclude_file(project: Project) -> Path | None:
    if project.common_dir is None:
        return None
    return project.common_dir / "info" / "exclude"


def drop_lines(project: Project, lines: list[str]) -> list[str]:
    """Take lines back out of .git/info/exclude. Return the steps."""
    target = exclude_file(project)
    if target is None or not target.is_file():
        return []
    old = target.read_text().splitlines()
    found = [line for line in lines if line in old]
    if found:
        target.write_text("\n".join(line for line in old if line not in found) + "\n")
        return [f"remove {', '.join(found)} from {target}"]
    return []


def remove_file(path: Path, checkout: Path) -> None:
    """Remove a file the tool wrote, and each folder that this leaves empty, up to the checkout."""
    path.unlink()
    for folder in path.parents:
        if folder == checkout or any(folder.iterdir()):
            return
        folder.rmdir()


def is_tracked(project: Project, rel: str, checkout: Path | None = None) -> bool:
    """True when git tracks rel in checkout (default: the discovery root)."""
    if not project.is_git:
        return False
    listed = run_git(checkout or project.root, "ls-files", "--", rel)
    return listed is None or bool(listed)  # git cannot say: never risk a write to a tracked file


def keep_out_of_git(memdir: Path) -> list[str]:
    """Exclude memdir in each work tree that holds it, then prove it with git.

    Return one problem for each work tree where git can still commit the memory.
    """
    problems = []
    real = memdir.resolve()
    for tree in enclosing_trees(real):
        rel = real.relative_to(tree).as_posix()
        env = tree_env()
        common = run_git(tree, "rev-parse", "--path-format=absolute", "--git-common-dir", env=env)
        if common:
            target = Path(common) / "info" / "exclude"
            line = f"/{rel}"
            if missing_lines(target, [line]):
                append_lines(target, [line])
        if run_git(tree, "ls-files", "--", rel, env=env):
            problems.append(
                f"git in {tree} tracks files in the memory folder {memdir}. "
                f"Remove them from its index: git -C {tree} rm -r --cached -- {rel}"
            )
        elif run_git(tree, "check-ignore", "-q", rel, env=env) is None:
            problems.append(
                f"git in {tree} does not ignore the memory folder {memdir}, so `git add -A` "
                "there can commit it. A .gitignore rule there overrides the exclude. "
                "Move the memory out of that work tree."
            )
    return problems


def exclude(project: Project, lines: list[str], dry_run: bool = False) -> list[str]:
    """Add lines to .git/info/exclude. Return the steps (done or planned)."""
    target = exclude_file(project)
    if target is None:
        return []
    missing = missing_lines(target, lines)
    if not missing:
        return []
    if not dry_run:
        append_lines(target, missing)
    return [f"add {', '.join(missing)} to {target}"]
