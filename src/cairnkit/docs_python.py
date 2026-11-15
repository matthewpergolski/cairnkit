"""Read Python files for `memory docs`: import roots, imports, docstrings, scripts, routes."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from cairnkit.docs_inventory import (
    PARSE_ERRORS,
    Route,
    first_sentence,
    parent,
    read_file,
    relative,
)

ROUTE_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "route", "api_route", "websocket"}
)
_SETTINGS_MODULE = re.compile(r"""DJANGO_SETTINGS_MODULE["']\s*,\s*["']([\w.]+)["']""")
_ROOT_URLCONF = re.compile(r"""^ROOT_URLCONF\s*=\s*["']([\w.]+)["']""", re.MULTILINE)


@dataclass(frozen=True)
class UrlPattern:
    route: str
    handler: str
    include: str | None  # the module that an include("...") names


@dataclass(frozen=True)
class DecoratedRoute:
    owner: str  # the name of the app or router object in `@owner.get("/path")`
    route: Route


@dataclass(frozen=True)
class PythonFacts:
    summary: str | None
    imports: tuple[tuple[str, ...], ...]  # per import: module names to try, most specific first
    names: dict[str, tuple[str, ...]]  # top-level `from x import name`: name -> modules to try
    runs_as_script: bool
    routes: tuple[DecoratedRoute, ...]  # from @x.get("/path") style decorators
    urlpatterns: tuple[UrlPattern, ...]
    settings_module: str | None  # manage.py: DJANGO_SETTINGS_MODULE
    root_urlconf: str | None  # settings: ROOT_URLCONF


def import_root(path: str, packages: set[str]) -> str:
    """The folder that Python puts on sys.path to import this file: the first non-package."""
    folder = parent(path)
    while folder and folder in packages:
        folder = parent(folder)
    return folder


def qualname(path: str, root: str) -> str:
    parts = relative(path, root)[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _relative_base(module: str, is_init: bool, level: int) -> str | None:
    parts = module.split(".") if module else []
    if not is_init:
        parts = parts[:-1]
    drop = level - 1
    if drop > len(parts):
        return None
    return ".".join(parts[: len(parts) - drop])


def _dotted(*names: str | None) -> str:
    return ".".join(name for name in names if name)


def _statements(tree: ast.Module) -> list[ast.AST]:
    """Each statement at any depth. Imports and function definitions are statements, so this
    finds all of them without a visit to each expression node."""
    found: list[ast.AST] = []
    stack: list[ast.AST] = list(reversed(tree.body))
    while stack:
        node = stack.pop()
        found.append(node)
        for name in ("body", "orelse", "finalbody", "handlers", "cases"):
            children = getattr(node, name, None)
            if isinstance(children, list):
                stack.extend(reversed(children))
    return found


def _import_names(nodes: list[ast.AST], module: str, is_init: bool) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                found.append(tuple(".".join(parts[:end]) for end in range(len(parts), 0, -1)))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = _relative_base(module, is_init, node.level)
                if base is None:
                    continue
            else:
                base = ""
            target = _dotted(base, node.module)
            for alias in node.names:
                if alias.name == "*":
                    found.append((target,))
                else:
                    found.append((_dotted(target, alias.name), target))
    return found


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    sides = [node.test.left, *node.test.comparators]
    names = {side.id for side in sides if isinstance(side, ast.Name)}
    values = {side.value for side in sides if isinstance(side, ast.Constant)}
    return names == {"__name__"} and values == {"__main__"}


def _decorator_routes(nodes: list[ast.AST], source: str) -> list[DecoratedRoute]:
    found: list[DecoratedRoute] = []
    for node in nodes:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                continue
            verb = deco.func.attr
            first = deco.args[0] if deco.args else None
            if verb not in ROUTE_METHODS or not isinstance(first, ast.Constant):
                continue
            if not isinstance(first.value, str) or not first.value.startswith("/"):
                continue
            owner = deco.func.value.id if isinstance(deco.func.value, ast.Name) else ""
            route = Route(_method(verb, deco), first.value, node.name, source)
            found.append(DecoratedRoute(owner, route))
    return found


def _top_names(tree: ast.Module, module: str, is_init: bool) -> dict[str, tuple[str, ...]]:
    """Each name a top-level `from x import name` binds, with the modules it may come from."""
    found: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            base = _relative_base(module, is_init, node.level) if node.level else ""
            if base is None:
                continue
            target = _dotted(base, node.module)
            for alias in node.names:
                found[alias.asname or alias.name] = (_dotted(target, alias.name), target)
    return found


def _method(verb: str, deco: ast.Call) -> str:
    if verb == "websocket":
        return "WS"
    if verb not in {"route", "api_route"}:
        return verb.upper()
    for keyword in deco.keywords:
        if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
            names = [
                item.value.upper()
                for item in keyword.value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            if names:
                return "/".join(names)
    return "ANY"


def _pattern_lists(value: ast.expr) -> list[ast.expr]:
    if isinstance(value, (ast.List, ast.Tuple)):
        return list(value.elts)
    if isinstance(value, ast.BinOp):
        return _pattern_lists(value.left) + _pattern_lists(value.right)
    return []


def _urlpatterns(tree: ast.Module) -> list[UrlPattern]:
    found: list[UrlPattern] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if not any(isinstance(t, ast.Name) and t.id == "urlpatterns" for t in targets):
            continue
        for item in _pattern_lists(value):
            pattern = _url_pattern(item)
            if pattern:
                found.append(pattern)
    return found


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _url_pattern(item: ast.expr) -> UrlPattern | None:
    if not isinstance(item, ast.Call) or _call_name(item.func) not in {"path", "re_path", "url"}:
        return None
    if len(item.args) < 2:
        return None
    route, view = item.args[0], item.args[1]
    if not (isinstance(route, ast.Constant) and isinstance(route.value, str)):
        return None
    if isinstance(view, ast.Call) and _call_name(view.func) == "include":
        first = view.args[0] if view.args else None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return UrlPattern(route.value, "", first.value)
        if isinstance(first, ast.Tuple) and first.elts:
            head = first.elts[0]
            if isinstance(head, ast.Constant) and isinstance(head.value, str):
                return UrlPattern(route.value, "", head.value)
        return UrlPattern(route.value, ast.unparse(view), None)
    return UrlPattern(route.value, ast.unparse(view), None)


_UNREAD = PythonFacts(None, (), {}, False, (), (), None, None)


def read_python(root: Path, path: str, module: str) -> PythonFacts:
    """What the file says. A file that cannot be read or parsed says nothing, so one odd file,
    such as a sum of 5000 terms that is too deep to walk, never stops the atlas."""
    text = read_file(root, path)
    if text is None:
        return _UNREAD
    try:
        return _facts(text, path, module)
    except (SyntaxError, *PARSE_ERRORS):
        return _UNREAD


def _facts(text: str, path: str, module: str) -> PythonFacts:
    tree = ast.parse(text, filename=path)
    is_init = path.endswith("/__init__.py") or path == "__init__.py"
    settings = _SETTINGS_MODULE.search(text) if path.endswith("manage.py") else None
    urlconf = _ROOT_URLCONF.search(text)
    nodes = _statements(tree)
    return PythonFacts(
        summary=first_sentence(ast.get_docstring(tree)),
        imports=tuple(_import_names(nodes, module, is_init)),
        names=_top_names(tree, module, is_init),
        runs_as_script=any(_is_main_guard(node) for node in tree.body),
        routes=tuple(_decorator_routes(nodes, path)),
        urlpatterns=tuple(_urlpatterns(tree)) if "urlpatterns" in text else (),
        settings_module=settings.group(1) if settings else None,
        root_urlconf=urlconf.group(1) if urlconf else None,
    )


class ModuleIndex:
    """Python modules by import name, per root. A name resolves in its own root first."""

    def __init__(self, modules: dict[str, dict[str, str]]):
        self._by_root = modules
        self._anywhere: dict[str, list[str]] = {}
        for root in sorted(modules):
            for name, path in modules[root].items():
                self._anywhere.setdefault(name, []).append(path)

    def find(self, root: str, name: str) -> str | None:
        own = self._by_root.get(root, {})
        if name in own:
            return own[name]
        others = self._anywhere.get(name, [])
        return others[0] if len(others) == 1 else None

    def resolve(self, root: str, names: tuple[str, ...]) -> str | None:
        """The file for the first name that is a project module."""
        for name in names:
            hit = self.find(root, name)
            if hit:
                return hit
        return None


def _mount(
    path: str,
    owner: str,
    facts: dict[str, PythonFacts],
    index: ModuleIndex,
    roots: dict[str, str],
) -> str | None:
    """The file that defines `owner` in `path("prefix/", owner.urls)`, when its routes are there."""
    names = facts[path].names.get(owner)
    target = index.resolve(roots[path], names) if names else None
    if target in facts and any(item.owner == owner for item in facts[target].routes):
        return target
    return None


def routes(facts: dict[str, PythonFacts], index: ModuleIndex, roots: dict[str, str]) -> list[Route]:
    """Routes from each Django urls module, with the prefix of each include that reaches it,
    and routes from `@app.get("/path")` style decorators, under their mount when one is found."""
    found: list[Route] = []
    seen: set[str] = set()
    mounted: set[tuple[str, str]] = set()

    def walk(path: str, prefix: str, depth: int) -> None:
        if path in seen or depth > 6:
            return
        seen.add(path)
        for pattern in facts[path].urlpatterns:
            full = prefix + pattern.route
            if pattern.include is None:
                owner = pattern.handler.removesuffix(".urls")
                is_mount = pattern.handler.endswith(".urls") and owner.isidentifier()
                target = _mount(path, owner, facts, index, roots) if is_mount else None
                if target is None:
                    found.append(Route("ANY", "/" + full, pattern.handler, path))
                    continue
                mounted.add((target, owner))
                base = "/" + full.strip("/") if full.strip("/") else ""
                found.extend(
                    Route(item.route.method, base + item.route.path, item.route.handler, target)
                    for item in facts[target].routes
                    if item.owner == owner
                )
                continue
            target = index.resolve(roots[path], (pattern.include,))
            if target and target in facts:
                walk(target, full, depth + 1)

    starts = sorted(
        index.resolve(roots[path], (item.root_urlconf,)) or ""
        for path, item in facts.items()
        if item.root_urlconf
    )
    for start in starts:
        if start in facts:
            walk(start, "", 0)
    for path in sorted(facts):
        if facts[path].urlpatterns and path not in seen:
            walk(path, "", 0)
    for path in sorted(facts):
        found.extend(item.route for item in facts[path].routes if (path, item.owner) not in mounted)
    return found
