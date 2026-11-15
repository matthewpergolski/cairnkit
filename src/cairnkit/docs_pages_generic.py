"""Atlas pages for a generic (non-cairnkit) project: one system page, one page per component."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from cairnkit.docs_cmd import _ATLAS_FRONT_MATTER, STATE_DIR, Page
from cairnkit.docs_inventory import (
    MAX_CODE_FILES,
    Component,
    EntryKind,
    EntryPoint,
    Language,
    ProjectInventory,
    Route,
    SourceFile,
    read_file,
    relative,
)

SYSTEM_COMPONENTS = 40
DIAGRAM_FILES = 30
DIAGRAM_NEIGHBORS = 12
TABLE_ROWS = 200
ENTRY_ROWS = 40


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _display(path: str) -> str:
    return path or "repo root"


def _quoted(text: str) -> str:
    return '"' + text.replace('"', "#quot;") + '"'


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _code(text: str) -> str:
    return "`" + _cell(text).replace("`", "'") + "`"


class _Ids:
    """Unique mermaid node ids within one diagram."""

    def __init__(self) -> None:
        self._taken: set[str] = set()

    def make(self, prefix: str, name: str) -> str:
        base = prefix + (re.sub(r"[^A-Za-z0-9_]", "_", name) or "root")
        found, count = base, 2
        while found in self._taken:
            found, count = f"{base}_{count}", count + 1
        self._taken.add(found)
        return found


class _Graph:
    """File and component edges, read once from the inventory."""

    def __init__(self, inv: ProjectInventory):
        self.files = {item.path: item for item in inv.files}
        self.importers: Counter[str] = Counter(
            target for item in inv.files for target in item.imports
        )
        self.links: Counter[tuple[str, str]] = Counter(
            (item.component, self.files[target].component)
            for item in inv.files
            for target in item.imports
            if self.files[target].component != item.component
        )

    def degree(self, path: str) -> int:
        return len(self.files[path].imports) + self.importers[path]

    def component_degree(self, folder: str) -> int:
        return sum(count for pair, count in self.links.items() if folder in pair)


def _page_ids(inv: ProjectInventory, root_id: str) -> dict[str, str]:
    taken = {root_id}
    found: dict[str, str] = {}
    for comp in inv.components:
        base = _slug(comp.path) or "repo-root"
        name, count = base, 2
        while name in taken:
            name, count = f"{base}-{count}", count + 1
        taken.add(name)
        found[comp.path] = name
    return found


def _languages(comp_files: tuple[str, ...], graph: _Graph) -> list[Language]:
    return sorted({graph.files[path].language for path in comp_files})


def _system_diagram(
    inv: ProjectInventory, graph: _Graph, page_ids: dict[str, str]
) -> tuple[str, dict[str, str]]:
    ids = _Ids()
    ranked = sorted(
        inv.components,
        key=lambda c: (-graph.component_degree(c.path), -len(c.files), c.path),
    )
    shown = {comp.path for comp in ranked[:SYSTEM_COMPONENTS]}
    node = {path: ids.make("c_", path) for path in sorted(shown)}
    lines = ["flowchart LR"]
    for root in sorted({comp.root for comp in inv.components if comp.path in shown}):
        members = [c for c in inv.components if c.root == root and c.path in shown]
        langs = sorted({lang for c in members for lang in _languages(c.files, graph)})
        label = f"{_display(root)} ({', '.join(langs)})"
        lines.append(f"    subgraph {ids.make('r_', root)}[{_quoted(label)}]")
        lines.extend(f"        {node[c.path]}[{_quoted(_display(c.path))}]" for c in members)
        lines.append("    end")
    for src, dst in sorted(graph.links):
        if src in shown and dst in shown:
            lines.append(f"    {node[src]} --> {node[dst]}")
    links = {node[path]: page_ids[path] for path in sorted(shown)}
    return "\n".join(lines), links


def _entry_rows(entries: list[EntryPoint]) -> list[str]:
    rows = ["| Kind | Name | Runs | Declared in |", "| --- | --- | --- | --- |"]
    rows.extend(
        f"| {entry.kind} | {_code(entry.name)} | {_code(entry.target)} | {_code(entry.source)} |"
        for entry in entries
    )
    return rows


def _route_rows(routes: list[Route]) -> list[str]:
    rows = ["| Method | Path | Handler | File |", "| --- | --- | --- | --- |"]
    rows.extend(
        f"| {route.method} | {_code(route.path)} | {_code(route.handler or '-')} "
        f"| {_code(route.source)} |"
        for route in routes
    )
    return rows


def _system_entry_rows(inv: ProjectInventory, graph: _Graph, page_ids: dict[str, str]) -> list[str]:
    """All entry points, with one row for each component that holds several helper scripts."""
    scripts: dict[str, list[EntryPoint]] = {}
    for entry in inv.entry_points:
        if entry.kind is EntryKind.PYTHON_SCRIPT:
            scripts.setdefault(_entry_component(entry, graph, inv) or "", []).append(entry)
    shown = [
        entry
        for entry in inv.entry_points
        if entry.kind is not EntryKind.PYTHON_SCRIPT
        or len(scripts[_entry_component(entry, graph, inv) or ""]) == 1
    ]
    rows = _entry_rows(shown[:ENTRY_ROWS])
    for folder, group in sorted(scripts.items()):
        if len(group) > 1:
            rows.append(
                f"| {EntryKind.PYTHON_SCRIPT} | {_files(len(group))} | `__main__` blocks "
                f"| [{_display(folder)}](components/{page_ids[folder]}.md) |"
            )
    if len(shown) > ENTRY_ROWS:
        rows.append(f"\n{len(shown) - ENTRY_ROWS} more are listed on the component pages.")
    return rows


def _entry_component(entry: EntryPoint, graph: _Graph, inv: ProjectInventory) -> str | None:
    if entry.file and entry.file in graph.files:
        return graph.files[entry.file].component
    folder = entry.source.rsplit("/", 1)[0] if "/" in entry.source else ""
    for comp in inv.components:
        if comp.path == folder:
            return comp.path
    return None


def _system_page(
    root: Path, inv: ProjectInventory, graph: _Graph, root_id: str, page_ids: dict[str, str]
) -> Page:
    parts = [
        f"# {inv.project_name}",
        inv.summary,
        "This atlas was written by `memory docs`. Open the project folder in "
        "[Nessa Docs](https://github.com/nessalabs/nessa-docs) to browse the "
        "diagrams. Boxes with a + open a deeper page.",
        "The root `sourceRevision` is the git commit inventoried for this system "
        "map. It is not a claim that every child page was behavior-reviewed at "
        "that commit. Child pages omit `sourceRevision`.",
    ]
    links: dict[str, str] = {}
    if not inv.components:
        parts.append("No Python or TypeScript/JavaScript source was found in this checkout.")
        parts.append(
            "```mermaid\nflowchart LR\n    Codebase[" + _quoted(inv.project_name) + "]\n```"
        )
    else:
        diagram, links = _system_diagram(inv, graph, page_ids)
        parts.append(
            "Each box is a component: a top-level package or folder in a source root. "
            "An arrow means that code in one component imports code in the other."
        )
        parts.append("```mermaid\n" + diagram + "\n```")
        if len(inv.components) > SYSTEM_COMPONENTS:
            parts.append(
                f"The diagram shows the {SYSTEM_COMPONENTS} most connected components of "
                f"{len(inv.components)}. The table lists all of them."
            )
        rows = [
            "| Root | Language | Marked by | Components | Files |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in inv.roots:
            comps = [c for c in inv.components if c.root == item.path]
            count = sum(
                1 for c in comps for path in c.files if graph.files[path].language is item.language
            )
            marks = ", ".join(_code(m) for m in item.manifests) or "-"
            rows.append(
                f"| {_code(_display(item.path))} | {item.language} | {marks} "
                f"| {len(comps)} | {count} |"
            )
        parts.append("## Source roots\n\n" + "\n".join(rows))
        rows = ["| Component | What it is | Files | Summary |", "| --- | --- | --- | --- |"]
        for comp in inv.components:
            rows.append(
                f"| [{_display(comp.path)}](components/{page_ids[comp.path]}.md) "
                f"| {comp.label} | {len(comp.files)} | {_cell(comp.summary or '-')} |"
            )
        parts.append("## Components\n\n" + "\n".join(rows))
    if inv.entry_points:
        parts.append("## Entry points\n\n" + "\n".join(_system_entry_rows(inv, graph, page_ids)))
    if inv.routes:
        counts = Counter(
            graph.files[r.source].component for r in inv.routes if r.source in graph.files
        )
        lines = [
            f"- [{_display(path)}](components/{page_ids[path]}.md): {count}"
            for path, count in sorted(counts.items())
        ]
        parts.append(
            f"## Routes\n\n{len(inv.routes)} HTTP routes. Each component page lists its own.\n\n"
            + "\n".join(lines)
        )
    if inv.unread:
        parts.append(
            f"This run read the first {MAX_CODE_FILES} code files in path "
            f"order and left out {inv.unread}, so that it stays fast on a large checkout."
        )
    sources = {"README.md"} if (root / "README.md").is_file() else set()
    sources.update(m for item in inv.roots for m in item.manifests)
    return Page(
        state_path="README.md",
        id=root_id,
        title=inv.project_name,
        kind="system",
        status="implemented",
        summary=inv.summary,
        parent=None,
        sources=tuple(sorted(sources)),
        diagram_links=links,
        body="\n\n".join(parts) + "\n",
        source_revision=inv.revision,
    )


def _component_diagram(
    comp: Component, graph: _Graph, page_ids: dict[str, str]
) -> tuple[str, dict[str, str]]:
    ids = _Ids()
    ranked = sorted(comp.files, key=lambda path: (-graph.degree(path), path))
    shown = sorted(ranked[:DIAGRAM_FILES])
    node = {path: ids.make("f_", relative(path, comp.path)) for path in shown}
    weight: Counter[str] = Counter()
    for path in shown:
        for target in graph.files[path].imports:
            other = graph.files[target].component
            if other != comp.path:
                weight[other] += 1
    for item in graph.files.values():
        if item.component != comp.path:
            for target in item.imports:
                if target in node:
                    weight[item.component] += 1
    near = sorted(sorted(weight), key=lambda path: (-weight[path], path))[:DIAGRAM_NEIGHBORS]
    outer = {path: ids.make("x_", path) for path in sorted(near)}
    lines = ["flowchart LR"]
    lines.extend(f"    {node[path]}[{_quoted(relative(path, comp.path))}]" for path in shown)
    lines.extend(f"    {outer[path]}[{_quoted(_display(path))}]" for path in sorted(near))
    edges: set[tuple[str, str]] = set()
    for path in shown:
        for target in graph.files[path].imports:
            if target in node:
                edges.add((node[path], node[target]))
            elif graph.files[target].component in outer:
                edges.add((node[path], outer[graph.files[target].component]))
    for item in graph.files.values():
        if item.component in outer:
            for target in item.imports:
                if target in node:
                    edges.add((outer[item.component], node[target]))
    lines.extend(f"    {src} --> {dst}" for src, dst in sorted(_reduce(edges)))
    return "\n".join(lines), {outer[path]: page_ids[path] for path in sorted(near)}


def _reduce(edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Leave out each arrow whose two ends a longer path still joins. One at a time, in order,
    so that what reaches what stays the same."""
    after: dict[str, set[str]] = {}
    for src, dst in edges:
        after.setdefault(src, set()).add(dst)
    kept = set(edges)
    for src, dst in sorted(edges):
        after[src].discard(dst)
        if _reaches(after, src, dst):
            kept.discard((src, dst))
        else:
            after[src].add(dst)
    return kept


def _reaches(after: dict[str, set[str]], start: str, goal: str) -> bool:
    stack, seen = [start], {start}
    while stack:
        for nxt in after.get(stack.pop(), ()):
            if nxt == goal:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def _component_page(
    inv: ProjectInventory, comp: Component, graph: _Graph, root_id: str, page_ids: dict[str, str]
) -> Page:
    langs = _languages(comp.files, graph)
    name = _display(comp.path)
    summary = comp.summary or f"{comp.label} with {_files(len(comp.files))}."
    facts = [f"{comp.label}.", f"Source root {_code(_display(comp.root))}."]
    if Language.PYTHON in langs and comp.path != comp.root:
        facts.append(f"Import name {_code(relative(comp.path, comp.root).replace('/', '.'))}.")
    facts.append(f"{_files(len(comp.files))}.")
    diagram, links = _component_diagram(comp, graph, page_ids)
    parts = [f"# {name}", *([comp.summary] if comp.summary else []), " ".join(facts)]
    note = (
        "An arrow means that one file imports the other. An arrow is left out when a longer "
        "path already joins the same two boxes."
    )
    if len(comp.files) > DIAGRAM_FILES:
        note += (
            f" The diagram shows the {DIAGRAM_FILES} most connected files of "
            f"{len(comp.files)}. The table lists all of them."
        )
    parts += [note, "```mermaid\n" + diagram + "\n```"]

    def link_list(pairs: list[tuple[str, int]]) -> str:
        if not pairs:
            return "Nothing else in this project."
        return "\n".join(
            f"- [{_display(path)}]({page_ids[path]}.md): {count} import(s)" for path, count in pairs
        )

    uses = sorted((dst, n) for (src, dst), n in graph.links.items() if src == comp.path)
    used_by = sorted((src, n) for (src, dst), n in graph.links.items() if dst == comp.path)
    parts.append("## Uses\n\n" + link_list(uses))
    parts.append("## Used by\n\n" + link_list(used_by))
    own = set(comp.files)
    entries = [e for e in inv.entry_points if _entry_component(e, graph, inv) == comp.path]
    if entries:
        parts.append("## Entry points\n\n" + "\n".join(_entry_rows(entries)))
    routes = [r for r in inv.routes if r.source in own]
    if routes:
        parts.append("## Routes\n\n" + "\n".join(_route_rows(routes)))
    rows = ["| File | Summary | Imported by |", "| --- | --- | --- |"]
    for path in comp.files[:TABLE_ROWS]:
        item: SourceFile = graph.files[path]
        rows.append(
            f"| {_code(relative(path, comp.path))} | {_cell(item.summary or '-')} "
            f"| {graph.importers[path]} |"
        )
    text = "## Files\n\n" + "\n".join(rows)
    if len(comp.files) > TABLE_ROWS:
        rest = len(comp.files) - TABLE_ROWS
        text += f"\n\n{rest} more {'file is' if rest == 1 else 'files are'} not listed."
    parts.append(text)
    return Page(
        state_path=f"components/{page_ids[comp.path]}.md",
        id=page_ids[comp.path],
        title=name,
        kind="module",
        status="implemented",
        summary=summary,
        parent=root_id,
        sources=comp.files,
        diagram_links=links,
        body="\n\n".join(parts) + "\n",
    )


def _files(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


_FRONT_MATTER = re.compile(r"\A---\n(.*?)^---$", re.DOTALL | re.MULTILINE)
_FRONT_ID = re.compile(r"^id: *(\S+) *$", re.MULTILINE)


def _hand_root_id(root: Path) -> str | None:
    """The id of a hand-written system page in docs/state, which stays and is the parent.
    Only the front matter gives it: an `id:` line in the body is text."""
    text = read_file(root, (STATE_DIR / "README.md").as_posix()) or ""
    front = None if _ATLAS_FRONT_MATTER.match(text) else _FRONT_MATTER.match(text)
    found = _FRONT_ID.search(front.group(1)) if front else None
    return found.group(1).strip("\"'") if found else None


def build_generic_pages(root: Path, inv: ProjectInventory) -> list[Page]:
    root_id = _hand_root_id(root) or _slug(inv.project_name) or "project"
    graph = _Graph(inv)
    page_ids = _page_ids(inv, root_id)
    pages = [_system_page(root, inv, graph, root_id, page_ids)]
    pages.extend(_component_page(inv, comp, graph, root_id, page_ids) for comp in inv.components)
    return pages
