"""Atlas pages for a generic (non-cairnkit) project inventory."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from cairnkit.docs_cmd import Page
from cairnkit.docs_inventory import (
    ProjectInventory,
    PythonModule,
    key_modules,
    node_id,
    package_edges,
)


def _root_id(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "project"


def _docstring(root: Path, mod: PythonModule) -> str:
    path = root / mod.rel_path
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return f"Module `{mod.qualname}`."
    doc = ast.get_docstring(tree)
    if doc:
        first = doc.strip().splitlines()[0].strip()
        if first:
            return first
    return f"Module `{mod.qualname}`."


def _public_names(root: Path, mod: PythonModule) -> tuple[str, ...]:
    path = root / mod.rel_path
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return ()
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and (
            not node.name.startswith("_")
        ):
            names.append(node.name)
    return tuple(sorted(names))


def _overview_mermaid(inv: ProjectInventory) -> str:
    lines = ["flowchart LR", "    Person[You and agents]", f"    Codebase[{inv.project_name}]"]
    lines.append("    Person --> Codebase")
    if inv.layout_entries:
        lines.append("    subgraph Layout[Top-level layout]")
        for entry in inv.layout_entries:
            lines.append(f"        {node_id(entry)}[{entry}]")
        lines.append("    end")
    packages = sorted({m.package for m in inv.python_modules})
    if packages:
        lines.append("    subgraph Packages[Packages]")
        for pkg in packages:
            lines.append(f"        {node_id(pkg)}[{pkg}]")
            lines.append(f"        Codebase --> {node_id(pkg)}")
        lines.append("    end")
    return "\n".join(lines)


def _architecture_mermaid(inv: ProjectInventory, keys: tuple[PythonModule, ...]) -> str:
    lines = ["flowchart TB"]
    for mod in keys:
        leaf = mod.qualname.rsplit(".", 1)[-1]
        lines.append(f"    {node_id(leaf)}[{leaf}]")
    for src, dst in package_edges(keys):
        lines.append(f"    {node_id(src)} --> {node_id(dst)}")
    return "\n".join(lines)


def _module_mermaid(mod: PythonModule, keys: tuple[PythonModule, ...]) -> str:
    by_qual = {m.qualname: m for m in keys}
    neighbors = {mod.qualname}
    for target in mod.imports_internal:
        if target in by_qual:
            neighbors.add(target)
    for other in keys:
        if mod.qualname in other.imports_internal:
            neighbors.add(other.qualname)
    nodes = sorted(neighbors)[:20]
    lines = ["flowchart LR"]
    for qual in nodes:
        leaf = qual.rsplit(".", 1)[-1]
        lines.append(f"    {node_id(leaf)}[{leaf}]")
    for qual in nodes:
        src = by_qual.get(qual)
        if not src:
            continue
        sleaf = qual.rsplit(".", 1)[-1]
        for target in src.imports_internal:
            if target in neighbors:
                dleaf = target.rsplit(".", 1)[-1]
                if sleaf != dleaf:
                    lines.append(f"    {node_id(sleaf)} --> {node_id(dleaf)}")
    return "\n".join(lines)


def build_generic_pages(root: Path, inv: ProjectInventory) -> list[Page]:
    root_id = _root_id(inv.project_name)
    keys = key_modules(inv)
    links: dict[str, str] = {}
    if keys:
        links["Architecture"] = "architecture"
    for mod in keys:
        leaf = mod.qualname.rsplit(".", 1)[-1]
        links[node_id(leaf)] = f"modules/{leaf}"

    sources = ["README.md"]
    if (root / "pyproject.toml").is_file():
        sources.append("pyproject.toml")
    sources.extend(m.rel_path for m in keys[:12])

    root_body = (
        f"# {inv.project_name}\n\n"
        f"{inv.summary}\n\n"
        "This atlas was written by `memory docs`. Open the project folder in "
        "[Nessa Docs](https://github.com/nessalabs/nessa-docs) to browse the "
        "diagrams. Boxes with a + open a deeper page.\n\n"
        "The root `sourceRevision` is the git commit inventoried for this system "
        "map. It is not a claim that every child page was behavior-reviewed at "
        "that commit. Child pages omit `sourceRevision`.\n\n"
        "```mermaid\n" + _overview_mermaid(inv) + "\n```\n"
    )
    pages = [
        Page(
            state_path="README.md",
            id=root_id,
            title=inv.project_name,
            kind="system",
            status="implemented",
            summary=inv.summary,
            parent=None,
            sources=tuple(sources),
            diagram_links=links,
            body=root_body,
            source_revision=inv.revision,
        )
    ]

    if keys:
        ep_lines = (
            "\n".join(f"- `{ep.name}` → `{ep.target}`" for ep in inv.entry_points) or "- (none)"
        )
        sec_lines = "\n".join(f"- {s.heading}" for s in inv.readme_sections) or "- (none)"
        arch_body = (
            "# Architecture\n\n"
            f"Import graph for key modules in `{inv.project_name}`.\n\n"
            "## Entry points\n\n"
            f"{ep_lines}\n\n"
            "## README sections\n\n"
            f"{sec_lines}\n\n"
            "```mermaid\n" + _architecture_mermaid(inv, keys) + "\n```\n"
        )
        pages.append(
            Page(
                state_path="architecture.md",
                id="architecture",
                title="Architecture",
                kind="service",
                status="implemented",
                summary=f"Import graph and entry points for {inv.project_name}.",
                parent=root_id,
                sources=tuple(m.rel_path for m in keys),
                diagram_links={},
                body=arch_body,
            )
        )

    for mod in keys:
        leaf = mod.qualname.rsplit(".", 1)[-1]
        apis = _public_names(root, mod)
        api_block = ", ".join(f"`{n}`" for n in apis) if apis else "(none listed)"
        body = (
            f"# {leaf}\n\n"
            f"{_docstring(root, mod)}\n\n"
            f"**Qualname:** `{mod.qualname}`\n\n"
            f"**Public names:** {api_block}\n\n"
            "```mermaid\n" + _module_mermaid(mod, keys) + "\n```\n"
        )
        pages.append(
            Page(
                state_path=f"modules/{leaf}.md",
                id=f"modules/{leaf}",
                title=leaf,
                kind="module",
                status="implemented",
                summary=_docstring(root, mod),
                parent=root_id,
                sources=(mod.rel_path,),
                diagram_links={},
                body=body,
            )
        )
    return pages
