"""Deterministic project inventory for `memory docs` (no model, no network)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SKIP_LAYOUT = {
    ".git",
    ".github",
    ".worktrees",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "venv",
    ".venv",
    "memory-bank",
    "docs",
}
SKIP_WALK = SKIP_LAYOUT | {"tests", "benchmarks"}
SKIP_MODULES = frozenset({"__init__", "__main__"})
CAIRNKIT_STEMS = frozenset({"memory", "schema", "state", "store"})
_HEADING = re.compile(r"^(#{2})\s+(.+?)\s*$")
_SLUG = re.compile(r"[^a-z0-9]+")


class ProjectKind(StrEnum):
    GENERIC = "generic"
    CAIRNKIT = "cairnkit"


@dataclass(frozen=True)
class EntryPoint:
    name: str
    target: str
    module: str


@dataclass(frozen=True)
class ReadmeSection:
    heading: str
    slug: str
    level: int


@dataclass(frozen=True)
class PythonModule:
    rel_path: str
    qualname: str
    package: str
    is_package_init: bool
    imports_internal: tuple[str, ...]
    imported_by_count: int


@dataclass(frozen=True)
class ProjectInventory:
    kind: ProjectKind
    project_name: str
    summary: str
    revision: str | None
    layout_entries: tuple[str, ...]
    python_modules: tuple[PythonModule, ...]
    entry_points: tuple[EntryPoint, ...]
    readme_sections: tuple[ReadmeSection, ...]
    primary_src_root: str | None


def _read_pyproject(root: Path) -> dict:
    path = root / "pyproject.toml"
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_name(root: Path) -> tuple[str, str]:
    data = _read_pyproject(root)
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    if project:
        name = str(project.get("name") or root.name)
        summary = str(project.get("description") or f"System map for {name}.")
        return name, summary
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            import json

            raw = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            raw = {}
        if isinstance(raw, dict):
            name = str(raw.get("name") or root.name)
            summary = str(raw.get("description") or f"System map for {name}.")
            return name, summary
    return root.name, f"System map for {root.name}."


def top_entries(root: Path, limit: int = 12) -> tuple[str, ...]:
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return ()
    names: list[str] = []
    for path in children:
        if path.name.startswith(".") or path.name in SKIP_LAYOUT:
            continue
        is_dir = path.is_dir() and not path.is_symlink()
        is_code = path.is_file() and path.suffix in {".py", ".ts", ".js", ".go", ".rs"}
        if is_dir or is_code:
            names.append(path.name)
    return tuple(names[:limit])


def _slug(text: str) -> str:
    return _SLUG.sub("-", text.lower()).strip("-") or "section"


def readme_sections(root: Path, limit: int = 8) -> tuple[ReadmeSection, ...]:
    path = root / "README.md"
    if not path.is_file():
        return ()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return ()
    found: list[ReadmeSection] = []
    for line in lines:
        match = _HEADING.match(line)
        if not match or len(match.group(1)) != 2:
            continue
        heading = match.group(2).strip()
        found.append(ReadmeSection(heading=heading, slug=_slug(heading), level=2))
        if len(found) >= limit:
            break
    return tuple(found)


def entry_points(root: Path) -> tuple[EntryPoint, ...]:
    data = _read_pyproject(root)
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    scripts = project.get("scripts") if isinstance(project.get("scripts"), dict) else {}
    found: list[EntryPoint] = []
    for name in sorted(scripts):
        target = scripts[name]
        if not isinstance(target, str) or ":" not in target:
            continue
        module = target.split(":", 1)[0].strip()
        found.append(EntryPoint(name=str(name), target=target.strip(), module=module))
    return tuple(found)


def detect_project_kind(root: Path) -> ProjectKind:
    data = _read_pyproject(root)
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    if str(project.get("name") or "") == "cairnkit":
        return ProjectKind.CAIRNKIT
    folder = root / "src" / "cairnkit"
    if folder.is_dir():
        stems = {p.stem for p in folder.glob("*.py")}
        if stems >= CAIRNKIT_STEMS:
            return ProjectKind.CAIRNKIT
    return ProjectKind.GENERIC


def revision(root: Path) -> str | None:
    from cairnkit.paths import run_git

    head = run_git(root, "rev-parse", "HEAD")
    if head and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        return head
    return None


def inventory(root: Path) -> ProjectInventory:
    name, summary = read_name(root)
    from cairnkit.docs_modules import discover_modules

    modules = discover_modules(root)
    primary = None
    if modules:
        # First package under src/
        src = root / "src"
        if src.is_dir():
            for child in sorted(src.iterdir(), key=lambda p: p.name.lower()):
                if child.is_dir() and (child / "__init__.py").is_file():
                    primary = f"src/{child.name}"
                    break
    return ProjectInventory(
        kind=detect_project_kind(root),
        project_name=name,
        summary=summary,
        revision=revision(root),
        layout_entries=top_entries(root),
        python_modules=modules,
        entry_points=entry_points(root),
        readme_sections=readme_sections(root),
        primary_src_root=primary,
    )


def key_modules(inv: ProjectInventory, limit: int = 16) -> tuple[PythonModule, ...]:
    if not inv.python_modules:
        return ()
    entry_mods = {ep.module for ep in inv.entry_points}
    selected: list[PythonModule] = []
    for mod in inv.python_modules:
        if mod.qualname in entry_mods or mod.qualname.rsplit(".", 1)[0] in entry_mods:
            selected.append(mod)
            continue
        if mod.imported_by_count >= 1:
            selected.append(mod)
            continue
        # Immediate package children always count for multi-module pipelines
        if mod.package and mod.qualname.count(".") == 1:
            selected.append(mod)
    # Stable unique by qualname
    seen: set[str] = set()
    ordered: list[PythonModule] = []
    for mod in sorted(selected, key=lambda m: m.qualname):
        if mod.qualname in seen:
            continue
        seen.add(mod.qualname)
        ordered.append(mod)
    return tuple(ordered[:limit])


def node_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", name.replace("-", "_").replace(".", "_"))
    return cleaned or "Part"


def package_edges(modules: tuple[PythonModule, ...]) -> tuple[tuple[str, str], ...]:
    """Directed edges between leaf module names (last qualname segment) via imports."""
    by_qual = {m.qualname: m for m in modules}
    edges: set[tuple[str, str]] = set()
    for mod in modules:
        src = mod.qualname.rsplit(".", 1)[-1]
        for target in mod.imports_internal:
            if target not in by_qual:
                continue
            dst = target.rsplit(".", 1)[-1]
            if src != dst:
                edges.add((src, dst))
    return tuple(sorted(edges))
