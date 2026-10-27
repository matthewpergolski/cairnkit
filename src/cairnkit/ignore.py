"""Keep local files out of git with .git/info/exclude (shared by all worktrees)."""

from __future__ import annotations

from pathlib import Path

from cairnkit.paths import Project, run_git

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
    return bool(run_git(checkout or project.root, "ls-files", "--", rel))


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
