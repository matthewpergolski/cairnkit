"""Atlas pages that describe cairnkit itself (session, fact lifecycle, CLI layout)."""

from __future__ import annotations

from pathlib import Path

from cairnkit.docs_cmd import Page
from cairnkit.docs_inventory import ProjectInventory, node_id

COMMAND_MODULES = frozenset(
    {
        "init",
        "migrate",
        "migrate_refs",
        "presets",
        "skills",
        "update",
        "instructions",
        "writing",
        "check",
        "hooks_cmd",
        "hookrun",
        "load",
        "reading",
        "tidy",
        "docs_cmd",
        "refresh",
        "autotidy",
        "followups",
    }
)


def _module_stems(inv: ProjectInventory) -> list[str]:
    return sorted(
        {
            m.qualname.rsplit(".", 1)[-1]
            for m in inv.python_modules
            if m.package == "cairnkit" or m.rel_path.startswith("src/cairnkit/")
        }
    )


def build_cairnkit_pages(root: Path, inv: ProjectInventory) -> list[Page]:
    root_id = "cairnkit"
    modules = _module_stems(inv)
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
    if inv.layout_entries:
        map_lines.append("    subgraph Layout[Top-level layout]")
        for entry in inv.layout_entries:
            map_lines.append(f"        {node_id(entry)}[{entry}]")
        map_lines.append("    end")

    root_body = (
        f"# {inv.project_name}\n\n"
        f"{inv.summary}\n\n"
        "This atlas was written by `memory docs`. Open the project folder in "
        "[Nessa Docs](https://github.com/nessalabs/nessa-docs) to browse the "
        "diagrams. Boxes with a + open a deeper page.\n\n"
        "The root `sourceRevision` is the git commit inventoried for this system "
        "map. It is not a claim that every child page was behavior-reviewed at "
        "that commit. Child template pages omit `sourceRevision`.\n\n"
        "```mermaid\n" + "\n".join(map_lines) + "\n```\n"
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
            sources=tuple(dict.fromkeys(sources)),
            diagram_links=links,
            body=root_body,
            source_revision=inv.revision,
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
        ),
    ]

    if modules:
        commands = [m for m in modules if m in COMMAND_MODULES]
        library = [m for m in modules if m not in COMMAND_MODULES and m != "cli"]
        arch_lines = ["flowchart TB", "    CLI[cli] --> Commands[command modules]"]
        if library:
            arch_lines.append("    CLI --> Library[library modules]")
        for mod in commands:
            arch_lines.append(f"    Commands --> {node_id(mod)}[{mod}]")
        for mod in library:
            arch_lines.append(f"    Library --> {node_id(mod)}[{mod}]")
        if "memory" in modules and "store" in modules:
            arch_lines.append("    memory --> store")
        if "load" in modules and "memory" in modules:
            arch_lines.append("    load --> memory")
        arch_body = (
            "# Package architecture\n\n"
            "The `memory` / `cairnkit` CLI dispatches into command modules. "
            "Shared helpers sit under library modules. "
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
            )
        )
    return pages
