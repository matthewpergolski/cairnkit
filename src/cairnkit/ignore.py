"""Keep local files out of git with .git/info/exclude (shared by all worktrees)."""

from __future__ import annotations

from pathlib import Path

from cairnkit.paths import Project, enclosing_trees, run_git, tree_env

HEADER = "# Private project memory (a link to a folder outside the repo)"


def missing_lines(path: Path, lines: list[str]) -> list[str]:
    have = set(path.read_text().splitlines()) if path.is_file() else set()
    return [line for line in lines if line not in have]


def append_lines(path: Path, lines: list[str], header: str = HEADER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text() if path.is_file() else ""
    prefix = "" if not old or old.endswith("\n") else "\n"
    with path.open("a") as fh:
        fh.write(prefix + header + "\n" + "\n".join(lines) + "\n")


def exclude_file(project: Project) -> Path | None:
    if project.common_dir is None:
        return None
    return project.common_dir / "info" / "exclude"


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
