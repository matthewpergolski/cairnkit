"""Is the check that a rule names really there? `enforced_by` is only a claim."""

from __future__ import annotations

import os
import re
from pathlib import Path

from cairnkit import detect, githook
from cairnkit.paths import Project


def _names_word(paths: list[Path], word: str) -> bool:
    pattern = re.compile(rf"(?<![\w-]){re.escape(word)}(?![\w-])")
    for path in paths:
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def _git_hook(project: Project, name: str) -> bool:
    if githook.is_running(project, name):
        return name != "commit-msg" or githook.guard_installed(project)
    folder = githook.git_folder(project) if project.is_git else None
    return bool(folder) and os.access(folder / name, os.X_OK)


def check_exists(project: Project, ref: str) -> bool | None:
    """True or False when a script can look. None for a type that it cannot look at."""
    kind, _, value = ref.partition(":")
    root = project.root
    if kind == "githook":
        return _git_hook(project, value)
    if kind == "test":
        return (root / value).exists()
    if kind == "ci":
        ci = [p for glob in detect.CI_GLOBS for p in sorted(root.glob(glob))]
        return _names_word(ci, value)
    if kind == "lint":
        return _names_word(detect.entries(root)[0], value.partition(":")[0])
    return None


def is_false(project: Project, state: dict) -> bool:
    """True when the rule names a check that is not there. A failed look claims nothing."""
    ref = state.get("enforced_by")
    if not ref:
        return False
    try:
        return check_exists(project, ref) is False
    except Exception:
        return False
