"""`memory docs`: write a Nessa Docs atlas under docs/state."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from cairnkit.memory import Memory, MemoryMissing
from cairnkit.paths import Project
from cairnkit.writing import fail

STATE_DIR = Path("docs") / "state"


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


@dataclass(frozen=True)
class Absent:
    pass


@dataclass(frozen=True)
class Current:
    pass


@dataclass(frozen=True)
class Stale:
    changed: tuple[str, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(set(self.changed)))
        if not ordered or ordered != self.changed:
            raise ValueError("Stale.changed must be non-empty, unique, and sorted")


AtlasFreshness = Absent | Current | Stale


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


def build_atlas(project: Project) -> list[Page]:
    from cairnkit.docs_inventory import ProjectKind, inventory
    from cairnkit.docs_pages_cairnkit import build_cairnkit_pages
    from cairnkit.docs_pages_generic import build_generic_pages

    inv = inventory(project.root)
    if inv.kind is ProjectKind.CAIRNKIT:
        return build_cairnkit_pages(project.root, inv)
    return build_generic_pages(project.root, inv)


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


def _prune_orphan_markdown(root: Path, pages: list[Page], *, dry_run: bool) -> list[Path]:
    state = root / STATE_DIR
    if not state.is_dir():
        return []
    keep = {root / STATE_DIR / page.state_path for page in pages}
    removed: list[Path] = []
    for path in sorted(state.rglob("*.md"), reverse=True):
        if path in keep:
            continue
        removed.append(path)
        if not dry_run:
            path.unlink(missing_ok=True)
    if not dry_run:
        for folder in sorted((p for p in state.rglob("*") if p.is_dir()), reverse=True):
            try:
                next(folder.iterdir())
            except StopIteration:
                folder.rmdir()
            except OSError:
                pass
    return removed


_SOURCE_REVISION_LINE = re.compile(r"^sourceRevision:[^\n]*\n", re.MULTILINE)
_UNREADABLE = object()


def _strip_source_revision(text: str) -> str:
    return _SOURCE_REVISION_LINE.sub("", text)


def _state_markdown(root: Path) -> dict[str, object] | None:
    state = root / STATE_DIR
    if not state.is_dir():
        return None
    paths = sorted(state.rglob("*.md"))
    if not paths:
        return None
    found: dict[str, object] = {}
    for path in paths:
        rel = path.relative_to(root).as_posix()
        try:
            found[rel] = _strip_source_revision(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            found[rel] = _UNREADABLE
    return found or None


def atlas_freshness(project: Project) -> AtlasFreshness:
    disk = _state_markdown(project.root)
    if disk is None:
        return Absent()
    fresh = {
        (STATE_DIR / page.state_path).as_posix(): _strip_source_revision(render_page(page))
        for page in build_atlas(project)
    }
    changed = tuple(
        sorted(rel for rel in set(fresh) | set(disk) if fresh.get(rel) != disk.get(rel))
    )
    if not changed:
        return Current()
    return Stale(changed)


def run_docs_check(project: Project) -> int:
    result = atlas_freshness(project)
    if isinstance(result, Stale):
        for path in result.changed:
            print(path)
        return 1
    return 0


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
    removed = _prune_orphan_markdown(project.root, pages, dry_run=dry_run) if force else []
    rels = [p.relative_to(project.root).as_posix() for p in paths]
    if dry_run:
        print(f"Would write {len(rels)} page(s) under {STATE_DIR.as_posix()}:")
        for rel in rels:
            print(f"  {rel}")
        for path in removed:
            print(f"  remove {path.relative_to(project.root).as_posix()}")
    else:
        print(f"Wrote {len(rels)} page(s) under {STATE_DIR.as_posix()}:")
        for rel in rels:
            print(f"  {rel}")
        for path in removed:
            print(f"  removed {path.relative_to(project.root).as_posix()}")
    print(
        "Browse with Nessa Docs: https://github.com/nessalabs/nessa-docs "
        "(open this project folder in the app)."
    )
    return 0
