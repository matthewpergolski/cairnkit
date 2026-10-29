"""`memory docs`: write a Nessa Docs atlas under docs/state."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from cairnkit.memory import Memory, MemoryMissing
from cairnkit.paths import Project, run_git
from cairnkit.writing import fail

STATE_DIR = Path("docs") / "state"
SKIP_TOP = {
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
ARCHITECTURE_MODULES = (
    "cli",
    "init",
    "memory",
    "store",
    "load",
    "hooks_cmd",
    "skills",
    "tidy",
    "update",
)


@dataclass(frozen=True)
class Page:
    state_path: str
    id: str
    title: str
    kind: str
    status: str
    summary: str
    parent: str | None
    sources: tuple[str, ...] = ()
    diagram_links: dict[str, str] = field(default_factory=dict)
    body: str = ""
    source_revision: str | None = None


def _yaml_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_./-]+", text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_page(page: Page) -> str:
    lines = ["---", f"id: {page.id}", f"title: {_yaml_scalar(page.title)}", f"kind: {page.kind}"]
    lines.append(f"status: {page.status}")
    lines.append(f"summary: {_yaml_scalar(page.summary)}")
    lines.append(f"parent: {_yaml_scalar(page.parent)}")
    if page.source_revision:
        lines.append(f'sourceRevision: "{page.source_revision}"')
    lines.append("sources:")
    if page.sources:
        lines.extend(f"  - {item}" for item in page.sources)
    else:
        lines.append("  []")
    if page.diagram_links:
        lines.append("diagramLinks:")
        lines.extend(f"  {key}: {value}" for key, value in page.diagram_links.items())
    else:
        lines.append("diagramLinks: {}")
    lines.append("---")
    lines.append("")
    lines.append(page.body.rstrip())
    lines.append("")
    return "\n".join(lines)


def _read_name(root: Path) -> tuple[str, str]:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError, UnicodeError):
            data = {}
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        name = str(project.get("name") or root.name)
        summary = str(project.get("description") or f"System map for {name}.")
        return name, summary
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            import json

            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            data = {}
        if isinstance(data, dict):
            name = str(data.get("name") or root.name)
            summary = str(data.get("description") or f"System map for {name}.")
            return name, summary
    return root.name, f"System map for {root.name}."


def _top_entries(root: Path) -> list[str]:
    try:
        children = sorted(root.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    names = []
    for path in children:
        if path.name.startswith(".") or path.name in SKIP_TOP:
            continue
        is_dir = path.is_dir() and not path.is_symlink()
        is_code = path.is_file() and path.suffix in {".py", ".ts", ".js", ".go", ".rs"}
        if is_dir or is_code:
            names.append(path.name)
    return names[:12]


def _architecture_modules(root: Path) -> list[str]:
    folder = root / "src" / "cairnkit"
    if not folder.is_dir():
        return []
    found = []
    for name in ARCHITECTURE_MODULES:
        if (folder / f"{name}.py").is_file():
            found.append(name)
    return found


def _revision(root: Path) -> str | None:
    head = run_git(root, "rev-parse", "HEAD")
    if head and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head):
        return head
    return None


def _node_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "", name.replace("-", "_").replace(".", "_"))
    return cleaned or "Part"


def build_atlas(project: Project) -> list[Page]:
    root = project.root
    name, summary = _read_name(root)
    rev = _revision(root)
    entries = _top_entries(root)
    modules = _architecture_modules(root)
    root_id = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "project"

    links: dict[str, str] = {"MemorySession": "agent-session", "FactStore": "fact-lifecycle"}
    nodes = ["Person[You and agents]", "MemorySession[Memory session]", "FactStore[Fact store]"]
    edges = ["Person --> MemorySession", "MemorySession --> FactStore"]
    sources = ["README.md"]
    if (root / "pyproject.toml").is_file():
        sources.append("pyproject.toml")
    if modules:
        links["Package"] = "architecture"
        nodes.insert(1, "Package[cairnkit package]")
        edges.insert(0, "Person --> Package")
        edges.insert(1, "Package --> MemorySession")
        sources.append("src/cairnkit/cli.py")

    map_lines = ["flowchart LR"]
    map_lines.extend(f"    {line}" for line in nodes)
    map_lines.extend(f"    {line}" for line in edges)
    if entries:
        map_lines.append("    subgraph Layout[Top-level layout]")
        for entry in entries:
            map_lines.append(f"        {_node_id(entry)}[{entry}]")
        map_lines.append("    end")

    root_body = (
        f"# {name}\n\n"
        f"{summary}\n\n"
        "This atlas was written by `memory docs`. Open the project folder in "
        "[Nessa Docs](https://github.com/nessalabs/nessa-docs) to browse the "
        "diagrams. Boxes with a + open a deeper page.\n\n"
        "```mermaid\n" + "\n".join(map_lines) + "\n```\n"
    )
    pages = [
        Page(
            state_path="README.md",
            id=root_id,
            title=name,
            kind="system",
            status="implemented",
            summary=summary,
            parent=None,
            sources=tuple(sources),
            diagram_links=links,
            body=root_body,
            source_revision=rev,
        ),
        Page(
            state_path="agent-session.md",
            id="agent-session",
            title="Agent session",
            kind="flow",
            status="implemented",
            summary="How an agent session loads facts, works, and stops.",
            parent=root_id,
            sources=("src/cairnkit/hookrun.py", "src/cairnkit/load.py")
            if modules
            else ("memory-bank",),
            diagram_links={},
            body=(
                "# Agent session\n\n"
                "A session starts with a hook that loads standing facts, then the "
                "agent works against the checkout, then a stop hook can tidy.\n\n"
                "```mermaid\n"
                "flowchart TD\n"
                "    Start[Session start hook] --> Load[memory load]\n"
                "    Load --> Work[Agent work in the checkout]\n"
                "    Work --> Add[memory add or change]\n"
                "    Work --> Search[memory search]\n"
                "    Add --> Stop[Session stop hook]\n"
                "    Search --> Stop\n"
                "```\n"
            ),
            source_revision=rev,
        ),
        Page(
            state_path="fact-lifecycle.md",
            id="fact-lifecycle",
            title="Fact lifecycle",
            kind="statechart",
            status="implemented",
            summary="A fact starts active, then can be superseded, expired, wrong, or promoted.",
            parent=root_id,
            sources=("src/cairnkit/schema.py", "src/cairnkit/state.py")
            if modules
            else ("memory-bank/facts",),
            diagram_links={},
            body=(
                "# Fact lifecycle\n\n"
                "New facts are active. Later change records move them to another "
                "status. Nothing is deleted except a purge for secrets.\n\n"
                "```mermaid\n"
                "stateDiagram-v2\n"
                "    [*] --> Active: memory add\n"
                "    Active --> Superseded: replaced by a newer fact\n"
                "    Active --> Expired: short-term end date or merged branch\n"
                "    Active --> Wrong: marked wrong\n"
                "    Active --> Promoted: held by a tracked file\n"
                "    Superseded --> [*]\n"
                "    Expired --> [*]\n"
                "    Wrong --> [*]\n"
                "    Promoted --> [*]\n"
                "```\n"
            ),
            source_revision=rev,
        ),
    ]

    if modules:
        arch_lines = ["flowchart TB", "    CLI[cli] --> Commands[command modules]"]
        for mod in modules:
            if mod == "cli":
                continue
            arch_lines.append(f"    Commands --> {_node_id(mod)}[{mod}]")
        arch_lines.append("    memory --> store")
        arch_lines.append("    load --> memory")
        arch_body = (
            "# Package architecture\n\n"
            "The `memory` / `cairnkit` CLI dispatches into small modules. "
            "Facts live outside the repo and are linked in as `memory-bank`.\n\n"
            "```mermaid\n" + "\n".join(arch_lines) + "\n```\n"
        )
        pages.append(
            Page(
                state_path="architecture.md",
                id="architecture",
                title="Package architecture",
                kind="service",
                status="implemented",
                summary="CLI entry points and the main cairnkit modules.",
                parent=root_id,
                sources=tuple(f"src/cairnkit/{m}.py" for m in modules),
                diagram_links={},
                body=arch_body,
                source_revision=rev,
            )
        )
    return pages


def write_atlas(root: Path, pages: list[Page], *, dry_run: bool) -> list[Path]:
    written: list[Path] = []
    for page in pages:
        path = root / STATE_DIR / page.state_path
        written.append(path)
        if dry_run:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_page(page), encoding="utf-8")
    return written


def run_docs(project: Project, path: str | None, dry_run: bool, force: bool) -> int:
    try:
        Memory.open(project, path)
    except MemoryMissing as exc:
        return fail(str(exc))

    out = project.root / STATE_DIR
    existing = sorted(out.rglob("*.md")) if out.is_dir() else []
    if existing and not force and not dry_run:
        return fail(
            f"{STATE_DIR.as_posix()} already exists ({len(existing)} Markdown file(s)). "
            "Re-run with --force to overwrite, or remove it first.\nNothing changed."
        )

    pages = build_atlas(project)
    paths = write_atlas(project.root, pages, dry_run=dry_run)
    rels = [p.relative_to(project.root).as_posix() for p in paths]
    if dry_run:
        print(f"Would write {len(rels)} page(s) under {STATE_DIR.as_posix()}:")
        for rel in rels:
            print(f"  {rel}")
    else:
        print(f"Wrote {len(rels)} page(s) under {STATE_DIR.as_posix()}:")
        for rel in rels:
            print(f"  {rel}")
    print(
        "Browse with Nessa Docs: https://github.com/nessalabs/nessa-docs "
        "(open this project folder in the app)."
    )
    return 0
