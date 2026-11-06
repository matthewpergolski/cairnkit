"""Deterministic project inventory for `memory docs` (no model, no network).

The shape: a project has source roots (a folder that imports resolve from). Each code file
belongs to one root and one component (a top-level package or folder in that root). Files
import other files. Entry points and routes name the file that declares them.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
import stat
import tomllib
from collections.abc import Iterable
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
# A folder with one of these names holds no source for the atlas: build output, installed
# packages, vendored code, generated migrations, tests, or test data.
SKIP_DIRS = SKIP_LAYOUT | {
    "out",
    "coverage",
    "site-packages",
    "storybook-static",
    "migrations",
    "fixtures",
    "tests",
    "test",
    "__tests__",
    "__mocks__",
    "e2e",
    "vendor",
}
_TEST_FILE = re.compile(
    r"(^test_.*\.py$|.*_test\.py$|^conftest\.py$|.*\.(test|spec|stories|story)\.\w+$)"
)
_GENERATED_FILE = re.compile(
    r".*(\.d\.[mc]?ts|\.generated\.\w+|\.gen\.\w+|\.min\.js|_pb2(_grpc)?\.py)$"
)
SKIP_MODULES = frozenset({"__init__", "__main__"})
CAIRNKIT_STEMS = frozenset({"memory", "schema", "state", "store"})
SCRIPT_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
MAX_CODE_FILES = 6000
MAX_FILE_BYTES = 1_000_000  # a bigger file is generated or data; the atlas reads it as empty
MAX_WALK = 50_000  # files listed in a folder with no git, so the run stays bounded
# What a parser raises on a file it cannot read. Deep nesting runs a parser out of stack:
# json and tomllib raise RecursionError, and the Python parser raises MemoryError.
PARSE_ERRORS = (ValueError, RecursionError, MemoryError)


class ProjectKind(StrEnum):
    GENERIC = "generic"
    CAIRNKIT = "cairnkit"


class Language(StrEnum):
    PYTHON = "Python"
    SCRIPT = "TypeScript/JavaScript"


class EntryKind(StrEnum):
    """In the order that a reader wants them: how the app starts first, helper scripts last."""

    DJANGO_MANAGE = "Django manage.py"
    CONSOLE_SCRIPT = "console script"
    PACKAGE_MAIN = "package main"
    PACKAGE_BIN = "package bin"
    PAGE_SCRIPT = "page script"
    NPM_SCRIPT = "package script"
    PYTHON_SCRIPT = "Python script"


@dataclass(frozen=True)
class SourceRoot:
    path: str  # repo-relative folder, "" for the repo root
    language: Language
    manifests: tuple[str, ...]  # repo-relative files that mark or configure this root


@dataclass(frozen=True)
class SourceFile:
    path: str
    language: Language
    root: str
    component: str
    summary: str | None
    imports: tuple[str, ...]  # repo-relative paths of the project files this file imports


@dataclass(frozen=True)
class Component:
    path: str  # repo-relative folder ("" for loose files at the repo root)
    root: str
    label: str  # what it is, for a reader: "Django app", "Python package", ...
    summary: str | None
    files: tuple[str, ...]


@dataclass(frozen=True)
class EntryPoint:
    kind: EntryKind
    name: str
    target: str
    source: str  # the file that declares it
    file: str | None  # the code file it runs, when known


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: str
    source: str


@dataclass(frozen=True)
class ProjectInventory:
    kind: ProjectKind
    project_name: str
    summary: str
    revision: str | None
    layout_entries: tuple[str, ...]
    roots: tuple[SourceRoot, ...]
    files: tuple[SourceFile, ...]
    components: tuple[Component, ...]
    entry_points: tuple[EntryPoint, ...]
    routes: tuple[Route, ...]
    unread: int  # code files past MAX_CODE_FILES, left out so the run stays bounded


def join(folder: str, name: str) -> str:
    return f"{folder}/{name}" if folder else name


def parent(path: str) -> str:
    return posixpath.dirname(path)


def under(path: str, folder: str) -> bool:
    return not folder or path.startswith(folder + "/")


def relative(path: str, folder: str) -> str:
    return path[len(folder) + 1 :] if folder else path


class ListingFailed(Exception):
    """git could not list the files of a repo. A walk would ignore .gitignore and differ."""


def _is_regular(path: Path) -> bool:
    """A plain file, not a link and not a device. A link can point out of the repo."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def read_file(root: Path, rel: str) -> str | None:
    """The text of one project file, or None when it is a link, is outside the repo, is bigger
    than MAX_FILE_BYTES, or is not UTF-8. A byte order mark goes."""
    path = root / rel
    real, home = os.path.realpath(path), os.path.realpath(root)
    if not _is_regular(path) or os.path.commonpath([real, home]) != home:
        return None
    try:
        with open(real, "rb") as fh:
            data = fh.read(MAX_FILE_BYTES + 1)
        return data.decode("utf-8-sig") if len(data) <= MAX_FILE_BYTES else None
    except (OSError, ValueError):
        return None


def _read_pyproject(root: Path, rel: str) -> dict:
    try:
        data = tomllib.loads(read_file(root, rel) or "")
    except PARSE_ERRORS:
        return {}
    return data if isinstance(data, dict) else {}


def read_json(root: Path, rel: str) -> dict:
    try:
        raw = json.loads(read_file(root, rel) or "null")
    except PARSE_ERRORS:
        return {}
    return raw if isinstance(raw, dict) else {}


def read_name(root: Path) -> tuple[str, str]:
    data = _read_pyproject(root, "pyproject.toml")
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    if project:
        name = str(project.get("name") or root.name)
        summary = str(project.get("description") or f"System map for {name}.")
        return name, summary
    raw = read_json(root, "package.json")
    if raw:
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


def detect_project_kind(root: Path) -> ProjectKind:
    data = _read_pyproject(root, "pyproject.toml")
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


def _kept(path: str) -> bool:
    parts = path.split("/")
    if any(part in SKIP_DIRS or part.startswith(".") for part in parts[:-1]):
        return False
    return not parts[-1].startswith(".")


def _walk(root: Path) -> Iterable[str]:
    """Plain files in a folder that is no git repo, in a fixed order, at most MAX_WALK."""
    count = 0
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        base = Path(folder).relative_to(root).as_posix()
        for name in sorted(names):
            path = name if base == "." else f"{base}/{name}"
            if _kept(path) and _is_regular(root / path):
                yield path
                count += 1
                if count >= MAX_WALK:
                    return


def project_paths(root: Path) -> list[str]:
    """Each plain file in the checkout that git tracks, or that is new and not ignored, outside
    skipped folders, sorted. A link is left out: it can point out of the repo."""
    from cairnkit.paths import run_git

    listed = run_git(
        root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", timeout=10.0
    )
    if listed is None:
        if os.path.lexists(root / ".git"):
            raise ListingFailed(
                f"git could not list the files in {root}, so the atlas could differ from one "
                "that git lists. Nothing changed."
            )
        return sorted(_walk(root))
    kept = {path for path in listed.split("\0") if path and _kept(path)}
    return sorted(path for path in kept if _is_regular(root / path))


def code_language(path: str) -> Language | None:
    name = path.rsplit("/", 1)[-1]
    if _TEST_FILE.match(name) or _GENERATED_FILE.match(name):
        return None
    if name.endswith(".py"):
        return Language.PYTHON
    if name.endswith(SCRIPT_SUFFIXES):
        return Language.SCRIPT
    return None


def first_sentence(text: str | None, limit: int = 200) -> str | None:
    """The first sentence of the first paragraph, cut to `limit` characters at a word."""
    lines: list[str] = []
    for line in (text or "").strip().splitlines():
        if not line.strip():
            break
        lines.append(line.strip())
    joined = " ".join(lines)
    end = re.search(r"(?<=[.!?])\s", joined)
    sentence = joined[: end.start()] if end else joined
    if len(sentence) > limit:
        sentence = sentence[:limit].rsplit(" ", 1)[0] + " ..."
    return sentence or None


def readme_line(root: Path, folder: str, paths: set[str]) -> str | None:
    """The first plain paragraph line of a README.md in the folder."""
    rel = join(folder, "README.md")
    if rel not in paths:
        return None
    lines = (read_file(root, rel) or "").splitlines()
    for index, line in enumerate(lines):
        text = line.strip()
        if text and not text.startswith(("#", "!", "[", "<", "|", "```", "---", ">")):
            return first_sentence("\n".join(lines[index:]))
    return None


@dataclass(frozen=True)
class _Read:
    roots: tuple[SourceRoot, ...]
    files: tuple[SourceFile, ...]
    components: tuple[Component, ...]
    entry_points: tuple[EntryPoint, ...]
    routes: tuple[Route, ...]
    unread: int


@dataclass
class _Draft:
    path: str
    language: Language
    root: str
    component: str
    summary: str | None
    imports: set[str]


@dataclass(frozen=True)
class _LanguageRead:
    roots: list[SourceRoot]
    entries: list[EntryPoint]
    routes: list[Route]
    labels: dict[str, str]  # component folder -> what it is, when a file says so
    summaries: dict[str, str]  # component folder -> summary from a manifest or package


def _name(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _deepest(path: str, folders: set[str]) -> str | None:
    folder = parent(path)
    while True:
        if folder in folders:
            return folder
        if not folder:
            return None
        folder = parent(folder)


def _component(path: str, base: str) -> str:
    rel = relative(path, base)
    return join(base, rel.split("/", 1)[0]) if "/" in rel else base


def _console_scripts(project: object) -> dict[str, str]:
    if not isinstance(project, dict):
        return {}
    merged: dict[str, str] = {}
    groups = project.get("entry-points")
    tables = [groups.get("console_scripts")] if isinstance(groups, dict) else []
    tables.append(project.get("scripts"))
    for table in tables:
        if isinstance(table, dict):
            for name, target in table.items():
                if isinstance(target, str) and ":" in target:
                    merged[str(name)] = target.strip()
    return merged


def _python(root: Path, paths: set[str], files: list[str], drafts: dict[str, _Draft]):
    from cairnkit import docs_python as py

    packages = {parent(path) for path in paths if _name(path) == "__init__.py"}
    roots = {path: py.import_root(path, packages) for path in files}
    modules: dict[str, dict[str, str]] = {}
    for path in files:
        modules.setdefault(roots[path], {})[py.qualname(path, roots[path])] = path
    index = py.ModuleIndex(modules)
    facts = {path: py.read_python(root, path, py.qualname(path, roots[path])) for path in files}
    for path in files:
        imports = {index.resolve(roots[path], names) for names in facts[path].imports}
        drafts[path] = _Draft(
            path=path,
            language=Language.PYTHON,
            root=roots[path],
            component=_component(path, roots[path]),
            summary=facts[path].summary,
            imports={hit for hit in imports if hit and hit != path},
        )
    entries: list[EntryPoint] = []
    for manifest in sorted(path for path in paths if _name(path) == "pyproject.toml"):
        project = _read_pyproject(root, manifest).get("project")
        folder = parent(manifest)
        for name, target in sorted(_console_scripts(project).items()):
            module = target.split(":", 1)[0].strip()
            hit = index.find(join(folder, "src"), module) or index.find(folder, module)
            entries.append(EntryPoint(EntryKind.CONSOLE_SCRIPT, name, target, manifest, hit))
    for path in files:
        item = facts[path]
        if _name(path) == "manage.py":
            target = f"settings {item.settings_module}" if item.settings_module else "manage.py"
            entries.append(EntryPoint(EntryKind.DJANGO_MANAGE, _name(path), target, path, path))
        elif item.runs_as_script:
            entries.append(
                EntryPoint(EntryKind.PYTHON_SCRIPT, _name(path), "__main__ block", path, path)
            )
    routes = py.routes(facts, index, roots)
    marks = ("pyproject.toml", "setup.py", "setup.cfg", "manage.py", "requirements.txt")
    found_roots = []
    for folder in sorted(set(roots.values())):
        homes = [folder, parent(folder)] if _name(folder) == "src" else [folder]
        manifests = sorted(join(home, mark) for home in homes for mark in marks)
        found_roots.append(
            SourceRoot(folder, Language.PYTHON, tuple(m for m in manifests if m in paths))
        )
    return _LanguageRead(
        roots=found_roots,
        entries=entries,
        routes=routes,
        labels={
            drafts[path].component: "Django settings and URLs"
            for path in files
            if facts[path].root_urlconf
        },
        summaries={
            parent(path): summary
            for path in files
            if _name(path) == "__init__.py" and (summary := facts[path].summary)
        },
    )


def _main(data: dict) -> str | None:
    for key in ("main", "module"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().removeprefix("./")
    return None


def _package_entries(folder: str, data: dict, resolver) -> list[EntryPoint]:
    manifest = join(folder, "package.json")
    entries: list[EntryPoint] = []
    scripts = data.get("scripts")
    for name, command in sorted(scripts.items() if isinstance(scripts, dict) else []):
        if isinstance(command, str):
            entries.append(EntryPoint(EntryKind.NPM_SCRIPT, str(name), command, manifest, None))
    main = _main(data)
    if main:
        hit = resolver.find_file(join(folder, main))
        entries.append(EntryPoint(EntryKind.PACKAGE_MAIN, "main", main, manifest, hit))
    bins = data.get("bin")
    if isinstance(bins, str):
        bins = {str(data.get("name") or _name(folder) or "bin"): bins}
    for name, target in sorted(bins.items() if isinstance(bins, dict) else []):
        if isinstance(target, str):
            hit = resolver.find_file(join(folder, target.removeprefix("./")))
            entries.append(EntryPoint(EntryKind.PACKAGE_BIN, str(name), target, manifest, hit))
    return entries


# A tag ends at the next `<` too, so an unclosed tag never scans past the tag after it.
_PAGE_SCRIPT = re.compile(r"""<script\b[^<>]*\bsrc=["']([^"':<>]+)["']""", re.IGNORECASE)


def _page_entries(root: Path, folder: str, paths: set[str], resolver) -> list[EntryPoint]:
    """The local scripts that the package's index.html loads (a Vite app's entry)."""
    page = join(folder, "index.html")
    if page not in paths:
        return []
    text = read_file(root, page) or ""
    found = []
    for src in sorted(set(_PAGE_SCRIPT.findall(text))):
        hit = resolver.find_file(join(folder, src.removeprefix("./").lstrip("/")))
        if hit:
            found.append(EntryPoint(EntryKind.PAGE_SCRIPT, "index.html", src, page, hit))
    return found


def _scripts(root: Path, paths: set[str], files: list[str], drafts: dict[str, _Draft]):
    from cairnkit import docs_script as js

    homes = {parent(path) for path in paths if _name(path) in js.MANIFEST_NAMES}
    owners = {path: home for path in files if (home := _deepest(path, homes)) is not None}
    used = sorted(set(owners.values()))
    packages = {
        folder: read_json(root, join(folder, "package.json"))
        for folder in sorted(homes)
        if join(folder, "package.json") in paths
    }
    workspaces = {
        str(data["name"]): js.Workspace(folder, _main(data))
        for folder, data in packages.items()
        if isinstance(data.get("name"), str)
    }
    aliases = {folder: js.read_aliases(root, folder, paths) for folder in used}
    resolver = js.ScriptResolver(set(owners), aliases, workspaces)
    has_src = {owners[path] for path in owners if under(path, join(owners[path], "src"))}
    for path, home in owners.items():
        base = join(home, "src") if home in has_src and under(path, join(home, "src")) else home
        text = read_file(root, path) or ""
        imports = {resolver.resolve(path, home, spec) for spec in js.specifiers(text)}
        drafts[path] = _Draft(
            path=path,
            language=Language.SCRIPT,
            root=home,
            component=_component(path, base),
            summary=js.leading_comment(text),
            imports={hit for hit in imports if hit and hit != path},
        )
    entries = [
        entry
        for folder in used
        for entry in [
            *_package_entries(folder, packages.get(folder, {}), resolver),
            *_page_entries(root, folder, paths, resolver),
        ]
    ]
    found_roots = [
        SourceRoot(
            folder,
            Language.SCRIPT,
            tuple(sorted(p for p in paths if parent(p) == folder and js.is_manifest(_name(p)))),
        )
        for folder in used
    ]
    return _LanguageRead(
        roots=found_roots,
        entries=entries,
        routes=[],
        labels={},
        summaries={
            folder: data["description"].strip()
            for folder, data in packages.items()
            if isinstance(data.get("description"), str) and data["description"].strip()
        },
    )


def _label(folder: str, group: list[_Draft], paths: set[str], labels: dict[str, str]) -> str:
    kinds: list[str] = []
    if any(draft.language is Language.PYTHON for draft in group):
        package = join(folder, "__init__.py") in paths
        if folder in labels:
            kinds.append(labels[folder])
        elif package and join(folder, "apps.py") in paths:
            kinds.append("Django app")
        else:
            kinds.append("Python package" if package else "Python modules")
    if any(draft.language is Language.SCRIPT for draft in group):
        typed = any(draft.path.endswith((".ts", ".tsx", ".mts", ".cts")) for draft in group)
        kinds.append("TypeScript folder" if typed else "JavaScript folder")
    return " and ".join(kinds)


def read_project(root: Path, listed: list[str]) -> _Read:
    paths = set(listed)
    code = [(path, lang) for path in listed if (lang := code_language(path))]
    unread = max(0, len(code) - MAX_CODE_FILES)
    code = code[:MAX_CODE_FILES]
    drafts: dict[str, _Draft] = {}
    python = _python(root, paths, [p for p, lang in code if lang is Language.PYTHON], drafts)
    script = _scripts(root, paths, [p for p, lang in code if lang is Language.SCRIPT], drafts)

    importers: dict[str, int] = {}
    for draft in drafts.values():
        for target in draft.imports:
            importers[target] = importers.get(target, 0) + 1
    for path in [p for p in drafts if _name(p) == "__init__.py"]:
        if not drafts[path].imports and not importers.get(path):
            del drafts[path]
    for draft in drafts.values():
        draft.imports &= drafts.keys()

    groups: dict[str, list[_Draft]] = {}
    for path in sorted(drafts):
        groups.setdefault(drafts[path].component, []).append(drafts[path])
    labels = {**script.labels, **python.labels}
    summaries = {**script.summaries, **python.summaries}
    components = tuple(
        Component(
            path=folder,
            root=group[0].root,
            label=_label(folder, group, paths, labels),
            summary=summaries.get(folder) or readme_line(root, folder, paths),
            files=tuple(draft.path for draft in group),
        )
        for folder, group in sorted(groups.items())
    )
    used_roots = {draft.root for draft in drafts.values()}
    return _Read(
        roots=tuple(
            sorted(
                (r for r in [*python.roots, *script.roots] if r.path in used_roots),
                key=lambda r: (r.path, r.language),
            )
        ),
        files=tuple(
            SourceFile(d.path, d.language, d.root, d.component, d.summary, tuple(sorted(d.imports)))
            for _, d in sorted(drafts.items())
        ),
        components=components,
        entry_points=tuple(
            sorted(
                [*python.entries, *script.entries],
                key=lambda e: (list(EntryKind).index(e.kind), e.source, e.name, e.target),
            )
        ),
        routes=tuple(
            sorted(
                set(python.routes + script.routes),
                key=lambda r: (r.source, r.path, r.method, r.handler),
            )
        ),
        unread=unread,
    )


def inventory(root: Path) -> ProjectInventory:
    name, summary = read_name(root)
    found = read_project(root, project_paths(root))
    return ProjectInventory(
        kind=detect_project_kind(root),
        project_name=name,
        summary=summary,
        revision=revision(root),
        layout_entries=top_entries(root),
        roots=found.roots,
        files=found.files,
        components=found.components,
        entry_points=found.entry_points,
        routes=found.routes,
        unread=found.unread,
    )


def node_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", name.replace("-", "_").replace(".", "_"))
    return cleaned or "Part"
