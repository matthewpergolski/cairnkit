"""Read TypeScript and JavaScript files for `memory docs`: imports, aliases, leading comments."""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from cairnkit.docs_inventory import (
    PARSE_ERRORS,
    SCRIPT_SUFFIXES,
    first_sentence,
    join,
    parent,
    read_file,
)

_FROM = re.compile(
    r"""\b(?:import|export)\s+(?:type\s+)?[\w*{}\s,$]*?\bfrom\s*["']([^"'\n]+)["']"""
)
_BARE = re.compile(r"""(?:^|[;\n])\s*import\s*["']([^"'\n]+)["']""")
_CALL = re.compile(r"""\b(?:import|require)\s*\(\s*["']([^"'\n]+)["']\s*\)""")
_SWAP = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}
_TOOL_COMMENT = re.compile(r"^(@|eslint|prettier|biome|ts-|jshint|global |istanbul)")
CONFIG_NAMES = ("tsconfig.json", "jsconfig.json")
MANIFEST_NAMES = frozenset({"package.json", *CONFIG_NAMES})
_CONFIG_FILE = re.compile(r"(tsconfig[\w.-]*|jsconfig)\.json")


def is_manifest(name: str) -> bool:
    return name == "package.json" or bool(_CONFIG_FILE.fullmatch(name))


@dataclass(frozen=True)
class Aliases:
    """Import aliases from one package's tsconfig/jsconfig files."""

    paths: tuple[tuple[str, tuple[str, ...]], ...]  # pattern -> repo-relative targets
    base_url: str | None  # repo-relative folder


def specifiers(text: str) -> list[str]:
    found = _FROM.findall(text) + _BARE.findall(text) + _CALL.findall(text)
    return sorted(set(found))


def leading_comment(text: str) -> str | None:
    """The first sentence of the comment that opens the file, unless it is a tool directive."""
    body = text.lstrip("﻿")
    if body.startswith("#!"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
    body = body.lstrip()
    if body.startswith("/*"):
        end = body.find("*/")
        lines = body[2 : end if end >= 0 else None].splitlines()
        lines = [line.strip().lstrip("*").strip() for line in lines]
    elif body.startswith("//"):
        lines = []
        for line in body.splitlines():
            if not line.strip().startswith("//"):
                break
            lines.append(line.strip()[2:].strip())
    else:
        return None
    text = "\n".join(lines).strip()
    return None if _TOOL_COMMENT.match(text) else first_sentence(text)


def _strip_jsonc(text: str) -> str:
    """Drop // and /* */ comments and trailing commas, outside strings."""
    out: list[str] = []
    index, size = 0, len(text)
    while index < size:
        char = text[index]
        if char == '"':
            end = index + 1
            while end < size and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[index : end + 1])
            index = end + 1
        elif text.startswith("//", index):
            newline = text.find("\n", index)
            index = size if newline < 0 else newline
        elif text.startswith("/*", index):
            close = text.find("*/", index + 2)
            index = size if close < 0 else close + 2
        else:
            out.append(char)
            index += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _read_config(root: Path, rel: str, depth: int = 0) -> tuple[dict, str | None, str | None]:
    """compilerOptions after `extends`, with the folders that baseUrl and paths are relative to."""
    try:
        data = json.loads(_strip_jsonc(read_file(root, rel) or "null"))
    except PARSE_ERRORS:
        return {}, None, None
    if not isinstance(data, dict):
        return {}, None, None
    options: dict = {}
    base_from = paths_from = None
    extends = data.get("extends")
    if isinstance(extends, str) and extends.startswith(".") and depth < 5:
        target = posixpath.normpath(join(parent(rel), extends))
        if not target.endswith(".json"):
            target += ".json"
        if not target.startswith(".."):
            options, base_from, paths_from = _read_config(root, target, depth + 1)
    own = data.get("compilerOptions")
    if isinstance(own, dict):
        if "baseUrl" in own:
            base_from = parent(rel)
        if "paths" in own:
            paths_from = parent(rel)
        options = {**options, **own}
    return options, base_from, paths_from


def read_aliases(root: Path, package: str, paths: set[str]) -> Aliases:
    names = sorted(
        path
        for path in paths
        if parent(path) == package and _CONFIG_FILE.fullmatch(path.rsplit("/", 1)[-1])
    )
    names.sort(key=lambda path: path.rsplit("/", 1)[-1] not in CONFIG_NAMES)
    patterns: dict[str, tuple[str, ...]] = {}
    base_url: str | None = None
    for rel in names:
        options, base_from, paths_from = _read_config(root, rel)
        base = options.get("baseUrl")
        base_dir = (
            posixpath.normpath(join(base_from or "", base)) if isinstance(base, str) else None
        )
        if base_dir == ".":
            base_dir = ""
        if base_url is None and base_dir is not None:
            base_url = base_dir
        table = options.get("paths")
        if not isinstance(table, dict):
            continue
        anchor = base_dir if base_dir is not None else (paths_from or "")
        for pattern, targets in table.items():
            if pattern in patterns or not isinstance(targets, list):
                continue
            patterns[pattern] = tuple(
                posixpath.normpath(join(anchor, target))
                for target in targets
                if isinstance(target, str)
            )
    ordered = sorted(patterns.items(), key=lambda item: (-len(item[0].split("*")[0]), item[0]))
    return Aliases(paths=tuple(ordered), base_url=base_url)


def _alias_bases(spec: str, aliases: Aliases) -> list[str]:
    for pattern, targets in aliases.paths:
        if "*" in pattern:
            head, _, tail = pattern.partition("*")
            if spec.startswith(head) and spec.endswith(tail) and len(spec) >= len(head + tail):
                middle = spec[len(head) : len(spec) - len(tail)]
                return [target.replace("*", middle, 1) for target in targets]
        elif spec == pattern:
            return list(targets)
    return []


def _candidates(base: str) -> list[str]:
    found = [base]
    stem, dot, ext = base.rpartition(".")
    if dot and "." + ext in _SWAP:
        found.extend(stem + swap for swap in _SWAP["." + ext])
    found.extend(base + suffix for suffix in SCRIPT_SUFFIXES)
    found.extend(join(base, "index") + suffix for suffix in SCRIPT_SUFFIXES)
    return found


@dataclass(frozen=True)
class Workspace:
    folder: str
    main: str | None


class ScriptResolver:
    def __init__(
        self,
        code: set[str],
        aliases: dict[str, Aliases],
        workspaces: dict[str, Workspace],
    ):
        self._code = code
        self._aliases = aliases
        self._workspaces = sorted(workspaces.items(), key=lambda item: -len(item[0]))

    def find_file(self, base: str) -> str | None:
        base = posixpath.normpath(base)
        if base.startswith("..") or base.startswith("/"):
            return None
        base = "" if base == "." else base
        for candidate in _candidates(base):
            if candidate in self._code:
                return candidate
        return None

    def resolve(self, path: str, package: str, spec: str) -> str | None:
        if spec.startswith(("./", "../")) or spec in {".", ".."}:
            return self.find_file(join(parent(path), spec) if parent(path) else spec)
        aliases = self._aliases.get(package)
        if aliases:
            for base in _alias_bases(spec, aliases):
                hit = self.find_file(base)
                if hit:
                    return hit
            if aliases.base_url is not None:
                hit = self.find_file(join(aliases.base_url, spec))
                if hit:
                    return hit
        for name, workspace in self._workspaces:
            if spec == name:
                bases = [join(workspace.folder, workspace.main)] if workspace.main else []
                bases += [join(workspace.folder, "index"), join(workspace.folder, "src/index")]
                return next(filter(None, map(self.find_file, bases)), None)
            if spec.startswith(name + "/"):
                rest = spec[len(name) + 1 :]
                bases = [join(workspace.folder, rest), join(workspace.folder, join("src", rest))]
                return next(filter(None, map(self.find_file, bases)), None)
        return None
