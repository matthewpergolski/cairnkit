"""Atlas pages for a generic (non-cairnkit) project inventory."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from cairnkit.docs_cmd import Page
from cairnkit.docs_inventory import ProjectInventory, PythonModule, node_id, page_qualnames


def _root_id(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "project"


def _page_id(qualname: str) -> str:
    return qualname.replace(".", "-")


def _docstring(root: Path, mod: PythonModule) -> str:
    path = root / mod.rel_path
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return f"Module `{mod.qualname}`."
    doc = ast.get_docstring(tree)
    if not doc:
        return f"Module `{mod.qualname}`."
    first = doc.strip().splitlines()[0].strip()
    return first or f"Module `{mod.qualname}`."


def _overview_mermaid(inv: ProjectInventory) -> str:
    lines = ["flowchart LR", "    Person[You and agents]", f"    Codebase[{inv.project_name}]"]
    lines.append("    Person --> Codebase")
    packages = sorted({mod.package for mod in inv.python_modules})
    if packages:
        lines.append("    subgraph Packages[Packages]")
        for pkg in packages:
            lines.append(f"        {node_id(pkg)}[{pkg}]")
            lines.append(f"        Codebase --> {node_id(pkg)}")
        lines.append("    end")
    if inv.layout_entries:
        lines.append("    subgraph Layout[Top-level layout]")
        for entry in inv.layout_entries:
            lines.append(f"        {node_id(entry)}[{entry}]")
        lines.append("    end")
    return "\n".join(lines)


def _architecture_mermaid(inv: ProjectInventory) -> str:
    modules = inv.python_modules
    lines = ["flowchart TB"]
    if not modules:
        lines.append(f"    Codebase[{inv.project_name}]")
        return "\n".join(lines)
    packages = sorted({mod.package for mod in modules})
    if len(packages) >= 2:
        edges = {
            (mod.package, target.split(".", 1)[0])
            for mod in modules
            for target in mod.imports_internal
            if mod.package != target.split(".", 1)[0]
        }
        for pkg in packages:
            lines.append(f"    {node_id(pkg)}[{pkg}]")
        for src, dst in sorted(edges):
            lines.append(f"    {node_id(src)} --> {node_id(dst)}")
        return "\n".join(lines)
    edges = {
        (mod.qualname, target)
        for mod in modules
        for target in mod.imports_internal
        if target != mod.qualname
    }
    for mod in modules:
        lines.append(f"    {node_id(mod.qualname)}[{mod.qualname}]")
    for src, dst in sorted(edges):
        lines.append(f"    {node_id(src)} --> {node_id(dst)}")
    return "\n".join(lines)


def _ego_mermaid(mod: PythonModule, modules: tuple[PythonModule, ...]) -> str:
    by_qual = {item.qualname: item for item in modules}
    neighbors = {mod.qualname}
    neighbors.update(target for target in mod.imports_internal if target in by_qual)
    for item in modules:
        if mod.qualname in item.imports_internal:
            neighbors.add(item.qualname)
    nodes = sorted(neighbors)[:20]
    lines = ["flowchart LR"]
    for qual in nodes:
        lines.append(f"    {node_id(qual)}[{qual}]")
    edges: set[tuple[str, str]] = set()
    for qual in nodes:
        src = by_qual.get(qual)
        if src is None:
            continue
        for target in src.imports_internal:
            if target in neighbors and target != qual:
                edges.add((qual, target))
    for src, dst in sorted(edges):
        lines.append(f"    {node_id(src)} --> {node_id(dst)}")
    return "\n".join(lines)


def _module_page(root: Path, inv: ProjectInventory, mod: PythonModule, parent: str) -> Page:
    summary = _docstring(root, mod)
    body = (
        f"# {mod.qualname.split('.')[-1]}\n\n"
        f"{summary}\n\n"
        f"`{mod.qualname}`\n\n"
        "```mermaid\n" + _ego_mermaid(mod, inv.python_modules) + "\n```\n"
    )
    return Page(
        state_path=f"modules/{_page_id(mod.qualname)}.md",
        id=_page_id(mod.qualname),
        title=mod.qualname.split(".")[-1],
        kind="module",
        status="implemented",
        summary=summary,
        parent=parent,
        sources=(mod.rel_path,),
        diagram_links={},
        body=body,
    )


def _subpackage_page(inv: ProjectInventory, qualname: str, parent: str) -> Page:
    children = tuple(mod for mod in inv.python_modules if mod.qualname.startswith(qualname + "."))
    listed = ", ".join(f"`{mod.qualname}`" for mod in children) or "(none)"
    lines = ["flowchart LR"]
    for mod in children:
        leaf = mod.qualname.split(".")[-1]
        lines.append(f"    {node_id(mod.qualname)}[{leaf}]")
    leaf = qualname.split(".")[-1]
    body = (
        f"# {leaf}\n\n"
        f"Package `{qualname}`.\n\n"
        f"Modules: {listed}\n\n"
        "```mermaid\n" + "\n".join(lines) + "\n```\n"
    )
    return Page(
        state_path=f"modules/{_page_id(qualname)}.md",
        id=_page_id(qualname),
        title=leaf,
        kind="module",
        status="implemented",
        summary=f"Package {qualname}.",
        parent=parent,
        sources=tuple(mod.rel_path for mod in children),
        diagram_links={},
        body=body,
    )


def _architecture_links(inv: ProjectInventory, selected: tuple[str, ...]) -> dict[str, str]:
    packages = {mod.package for mod in inv.python_modules}
    if len(packages) >= 2:
        return {}
    known = {mod.qualname for mod in inv.python_modules}
    return {node_id(qual): _page_id(qual) for qual in selected if qual in known}


def build_generic_pages(root: Path, inv: ProjectInventory) -> list[Page]:
    root_id = _root_id(inv.project_name)
    sources = ["README.md"]
    if (root / "pyproject.toml").is_file():
        sources.append("pyproject.toml")
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
            diagram_links={"Codebase": "architecture"},
            body=root_body,
            source_revision=inv.revision,
        )
    ]
    selected = page_qualnames(inv)
    by_qual = {mod.qualname: mod for mod in inv.python_modules}
    ep_lines = "\n".join(f"- `{ep.name}`: `{ep.target}`" for ep in inv.entry_points) or "- (none)"
    sec_lines = "\n".join(f"- {section.heading}" for section in inv.readme_sections) or "- (none)"
    arch_body = (
        "# Architecture\n\n"
        f"Import graph for `{inv.project_name}`.\n\n"
        "## Entry points\n\n"
        f"{ep_lines}\n\n"
        "## README sections\n\n"
        f"{sec_lines}\n\n"
        "```mermaid\n" + _architecture_mermaid(inv) + "\n```\n"
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
            sources=tuple(sorted(mod.rel_path for mod in inv.python_modules)),
            diagram_links=_architecture_links(inv, selected),
            body=arch_body,
        )
    )
    for qual in selected:
        mod = by_qual.get(qual)
        if mod is None:
            pages.append(_subpackage_page(inv, qual, "architecture"))
        else:
            pages.append(_module_page(root, inv, mod, "architecture"))
    return pages
