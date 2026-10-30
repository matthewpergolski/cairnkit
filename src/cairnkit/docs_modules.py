"""Discover Python modules and their internal import edges for `memory docs`."""

from __future__ import annotations

import ast
from pathlib import Path

from cairnkit.docs_inventory import SKIP_MODULES, SKIP_WALK, PythonModule, read_name


def _package_roots(root: Path) -> list[Path]:
    src = root / "src"
    if src.is_dir():
        kids = sorted(
            (
                p
                for p in src.iterdir()
                if p.is_dir() and not p.is_symlink() and (p / "__init__.py").is_file()
            ),
            key=lambda p: p.name.lower(),
        )
        if kids:
            return kids
    name, _ = read_name(root)
    named = src / name
    if named.is_dir() and (named / "__init__.py").is_file():
        return [named]
    return sorted(
        (
            p
            for p in root.iterdir()
            if p.is_dir()
            and not p.is_symlink()
            and p.name not in SKIP_WALK
            and not p.name.startswith(".")
            and (p / "__init__.py").is_file()
        ),
        key=lambda p: p.name.lower(),
    )


def _match_known(name: str, known: set[str], package: str) -> str | None:
    if name in known:
        return name
    for k in sorted(known, key=len, reverse=True):
        if name.startswith(k + "."):
            return k
    if name.split(".", 1)[0] != package:
        return None
    for k in sorted(known, key=len, reverse=True):
        if name == k or name.startswith(k + "."):
            return k
    return None


def _parse_imports(path: Path, known: set[str], package: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return ()
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                hit = _match_known(alias.name, known, package)
                if hit:
                    found.add(hit)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            hit = _match_known(node.module, known, package)
            if hit:
                found.add(hit)
    return tuple(sorted(found))


def _relative_imports(path: Path, qualname: str, known: set[str]) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return ()
    parts = qualname.split(".")
    found: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.level:
            continue
        parent = parts if path.name == "__init__.py" else parts[:-1]
        if node.level > len(parent):
            continue
        base = ".".join(parent[: len(parent) - node.level])
        target = f"{base}.{node.module}" if node.module and base else (node.module or base)
        for k in sorted(known, key=len, reverse=True):
            if target == k or target.startswith(k + "."):
                found.add(k)
                break
    return tuple(sorted(found))


def discover_modules(root: Path) -> tuple[PythonModule, ...]:
    files: list[tuple[Path, Path]] = []
    for package_root in _package_roots(root):
        try:
            paths = sorted(package_root.rglob("*.py"))
        except OSError:
            continue
        for path in paths:
            if any(
                part in SKIP_WALK or part.startswith(".") for part in path.relative_to(root).parts
            ):
                continue
            files.append((package_root, path))
    prelim: list[tuple[Path, Path, str, str]] = []
    for package_root, path in files:
        if package_root.parent.name == "src":
            qual = ".".join(path.relative_to(package_root.parent).with_suffix("").parts)
        else:
            qual = ".".join(
                [package_root.name, *path.relative_to(package_root).with_suffix("").parts]
            )
        if qual.endswith(".__init__"):
            qual = qual[: -len(".__init__")]
        if path.stem in SKIP_MODULES:
            continue
        package = qual.split(".", 1)[0] if qual else package_root.name
        prelim.append((package_root, path, qual, package))
    known = {qual for _, _, qual, _ in prelim}
    modules: list[PythonModule] = []
    imports_map: dict[str, tuple[str, ...]] = {}
    for _package_root, path, qual, package in prelim:
        abs_imports = set(_parse_imports(path, known, package))
        rel_imports = set(_relative_imports(path, qual, known))
        internal = tuple(sorted((abs_imports | rel_imports) - {qual}))
        imports_map[qual] = internal
        modules.append(
            PythonModule(
                rel_path=path.relative_to(root).as_posix(),
                qualname=qual,
                package=package,
                is_package_init=False,
                imports_internal=internal,
                imported_by_count=0,
            )
        )
    counts = {m.qualname: 0 for m in modules}
    for targets in imports_map.values():
        for t in targets:
            if t in counts:
                counts[t] += 1
    return tuple(
        PythonModule(
            rel_path=m.rel_path,
            qualname=m.qualname,
            package=m.package,
            is_package_init=m.is_package_init,
            imports_internal=m.imports_internal,
            imported_by_count=counts.get(m.qualname, 0),
        )
        for m in modules
    )
