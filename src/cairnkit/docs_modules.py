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


def _resolve(name: str, known: set[str]) -> str | None:
    if name in known:
        return name
    best: str | None = None
    for qual in known:
        if name.startswith(qual + ".") and (best is None or len(qual) > len(best)):
            best = qual
    return best


def _relative_prefix(qualname: str, level: int) -> str | None:
    parts = qualname.split(".")[:-1]
    drop = level - 1
    if drop > len(parts):
        return None
    if drop:
        parts = parts[: len(parts) - drop]
    return ".".join(parts)


def _internal_imports(path: Path, qualname: str, known: set[str]) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError):
        return ()
    found: set[str] = set()
    for node in tree.body:
        targets: list[str] = []
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            prefix = _relative_prefix(qualname, node.level)
            if prefix is None:
                continue
            if node.module:
                targets.append(f"{prefix}.{node.module}" if prefix else node.module)
            else:
                targets.extend(
                    f"{prefix}.{alias.name}" if prefix else alias.name for alias in node.names
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.append(node.module)
            targets.extend(f"{node.module}.{alias.name}" for alias in node.names)
        for target in targets:
            hit = _resolve(target, known)
            if hit:
                found.add(hit)
    found.discard(qualname)
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
    for _package_root, path, qual, package in prelim:
        modules.append(
            PythonModule(
                rel_path=path.relative_to(root).as_posix(),
                qualname=qual,
                package=package,
                is_package_init=False,
                imports_internal=_internal_imports(path, qual, known),
                imported_by_count=0,
            )
        )
    counts = {mod.qualname: 0 for mod in modules}
    for mod in modules:
        for target in mod.imports_internal:
            if target in counts:
                counts[target] += 1
    ranked = [
        PythonModule(
            rel_path=mod.rel_path,
            qualname=mod.qualname,
            package=mod.package,
            is_package_init=False,
            imports_internal=mod.imports_internal,
            imported_by_count=counts[mod.qualname],
        )
        for mod in modules
    ]
    return tuple(sorted(ranked, key=lambda mod: (mod.qualname, mod.rel_path)))
