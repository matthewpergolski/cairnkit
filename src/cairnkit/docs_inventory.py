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


def _script_tables(project: dict) -> list[dict]:
    tables: list[dict] = []
    groups = project.get("entry-points")
    if isinstance(groups, dict) and isinstance(groups.get("console_scripts"), dict):
        tables.append(groups["console_scripts"])
    scripts = project.get("scripts")
    if isinstance(scripts, dict):
        tables.append(scripts)
    return tables


def entry_points(root: Path) -> tuple[EntryPoint, ...]:
    data = _read_pyproject(root)
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    merged: dict[str, str] = {}
    for table in _script_tables(project):
        for name, target in table.items():
            if isinstance(target, str) and ":" in target:
                merged[str(name)] = target.strip()
    found: list[EntryPoint] = []
    for name in sorted(merged):
        target = merged[name]
        module = target.split(":", 1)[0].strip()
        found.append(EntryPoint(name=name, target=target, module=module))
    return tuple(found)


def detect_project_kind(root: Path) -> ProjectKind:
    data = _read_pyproject(root)
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    if str(project.get("name") or "") == "cairnkit":
        return ProjectKind.CAIRNKIT
    folder = root / "src" / "cairnkit"
    if folder.is_dir() and (folder / "__init__.py").is_file():
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


def _primary_src_root(root: Path, project_name: str) -> str | None:
    src = root / "src"
    if not src.is_dir():
        return None
    try:
        children = sorted(src.iterdir(), key=lambda path: path.name.lower())
    except OSError:
        return None
    packages = [
        child.name
        for child in children
        if child.is_dir() and not child.is_symlink() and (child / "__init__.py").is_file()
    ]
    if not packages:
        return None
    chosen = project_name if project_name in packages else packages[0]
    return f"src/{chosen}"


def inventory(root: Path) -> ProjectInventory:
    name, summary = read_name(root)
    from cairnkit.docs_modules import discover_modules

    return ProjectInventory(
        kind=detect_project_kind(root),
        project_name=name,
        summary=summary,
        revision=revision(root),
        layout_entries=top_entries(root),
        python_modules=discover_modules(root),
        entry_points=entry_points(root),
        readme_sections=readme_sections(root),
        primary_src_root=_primary_src_root(root, name),
    )


def page_qualnames(inv: ProjectInventory, limit: int = 16) -> tuple[str, ...]:
    by_qual = {mod.qualname: mod for mod in inv.python_modules}
    chosen = {mod.qualname for mod in inv.python_modules if mod.imported_by_count >= 2}
    chosen.update(point.module for point in inv.entry_points if point.module in by_qual)
    if inv.primary_src_root:
        package = inv.primary_src_root.rsplit("/", 1)[-1]
        for mod in inv.python_modules:
            parts = mod.qualname.split(".")
            if len(parts) >= 3 and parts[0] == package:
                chosen.add(f"{parts[0]}.{parts[1]}")

    def sort_key(qual: str) -> tuple[str, str]:
        mod = by_qual.get(qual)
        return (qual, mod.rel_path if mod else qual)

    return tuple(sorted(chosen, key=sort_key)[:limit])


def node_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", name.replace("-", "_").replace(".", "_"))
    return cleaned or "Part"
