"""Hook adapters: write each agent tool's local hook config.

Formats follow each tool's public hook docs (checked 2026-10-22):

- Claude Code: `.claude/settings.local.json`, events `SessionStart` and `Stop`.
  SessionStart stdout is added to the context. A Stop hook that prints
  `{"decision": "block", "reason": ...}` makes the agent continue.
- Codex: `.codex/hooks.json`, same shape. Stop must print JSON on exit 0.
  Project hooks run only in a trusted project, after review in `/hooks`.
- Cursor: `.cursor/hooks.json` (`version: 1`), events `sessionStart`
  (JSON `additional_context`) and `stop` (JSON `followup_message`, capped by
  `loop_limit`).

The core never depends on these tools. Only this module names them.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from cairnkit.ignore import exclude, is_tracked
from cairnkit.paths import Project

MARK = "cairnkit hook"
# What a hook command held before the rename. Install replaces it; uninstall removes it.
MARKS = (MARK, "project_memory hook")
EXPERIMENTAL = {"codex", "cursor"}


def hook_command(event: str, agent: str) -> str:
    """The command a hook runs. It uses this Python, so PATH does not matter."""
    return f"{shlex.quote(sys.executable)} -m cairnkit hook {event} --agent {agent}"


def _ours(handler: dict) -> bool:
    command = str(handler.get("command", ""))
    return any(mark in command for mark in MARKS)


@dataclass
class Adapter:
    name: str
    rel: str  # config file, relative to the checkout
    shared: tuple[str, ...] = ()  # other files where the tool reads hooks (often tracked)

    def add(self, data: dict) -> dict:
        raise NotImplementedError

    def remove(self, data: dict) -> dict:
        raise NotImplementedError


class NestedAdapter(Adapter):
    """Claude Code and Codex: hooks -> Event -> [ {matcher, hooks: [handler]} ]."""

    def __init__(self, name: str, rel: str, start_matcher: str, shared: tuple[str, ...] = ()):
        super().__init__(name, rel, shared)
        self.start_matcher = start_matcher

    def _groups(self) -> dict[str, dict]:
        start = {"type": "command", "command": hook_command("session-start", self.name)}
        stop = {"type": "command", "command": hook_command("stop", self.name), "timeout": 30}
        return {
            "SessionStart": {"matcher": self.start_matcher, "hooks": [{**start, "timeout": 10}]},
            "Stop": {"hooks": [stop]},
        }

    def remove(self, data: dict) -> dict:
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            return data
        for event in list(hooks):
            groups = []
            for group in hooks[event] if isinstance(hooks[event], list) else []:
                kept = [h for h in group.get("hooks", []) if not _ours(h)]
                if kept:
                    groups.append({**group, "hooks": kept})
            if groups:
                hooks[event] = groups
            else:
                del hooks[event]
        if not hooks:
            del data["hooks"]
        return data

    def add(self, data: dict) -> dict:
        data = self.remove(data)
        hooks = data.setdefault("hooks", {})
        for event, group in self._groups().items():
            hooks.setdefault(event, []).append(group)
        return data


class CursorAdapter(Adapter):
    """Cursor: {version: 1, hooks: {event: [ {command, ...} ]}}."""

    def remove(self, data: dict) -> dict:
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            return data
        for event in list(hooks):
            kept = [h for h in hooks[event] if not _ours(h)]
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
        return data

    def add(self, data: dict) -> dict:
        data = self.remove(data)
        data.setdefault("version", 1)
        hooks = data.setdefault("hooks", {})
        hooks.setdefault("sessionStart", []).append(
            {"command": hook_command("session-start", "cursor"), "timeout": 10}
        )
        hooks.setdefault("stop", []).append(
            {"command": hook_command("stop", "cursor"), "timeout": 30, "loop_limit": 1}
        )
        return data


ADAPTERS: dict[str, Adapter] = {
    "claude": NestedAdapter(
        "claude",
        ".claude/settings.local.json",
        "startup|resume|clear|compact",
        shared=(".claude/settings.json",),
    ),
    "codex": NestedAdapter("codex", ".codex/hooks.json", "startup|resume"),
    "cursor": CursorAdapter("cursor", ".cursor/hooks.json"),
}
BINARIES = {"claude": "claude", "codex": "codex", "cursor": "cursor-agent"}


def detect(project: Project) -> list[str]:
    found = []
    for name in ADAPTERS:
        folder = "." + name
        if (
            (project.main_root / folder).is_dir()
            or (project.root / folder).is_dir()
            or shutil.which(BINARIES[name])
        ):
            found.append(name)
    return found or ["generic"]


def _empty(data: dict) -> bool:
    return not data or data == {"version": 1} or data == {"version": 1, "hooks": {}}


class BadConfig(Exception):
    pass


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except ValueError as exc:
        raise BadConfig(
            f"{path} is not valid JSON ({exc}); fix it first. Nothing changed."
        ) from exc
    if not isinstance(data, dict):
        raise BadConfig(f"{path} does not hold a JSON object. Nothing changed.")
    return data


def apply(
    project: Project, name: str, install: bool, dry_run: bool, checkouts: list[Path] | None = None
) -> list[str]:
    """Install or remove one adapter in every checkout, or in `checkouts`. Return the steps."""
    adapter = ADAPTERS[name]
    steps: list[str] = []
    for checkout in project.checkouts if checkouts is None else checkouts:
        path = checkout / adapter.rel
        if is_tracked(project, adapter.rel):
            if install:
                start, stop = hook_command("session-start", name), hook_command("stop", name)
                steps.append(
                    f"skip {path}: it is tracked by git. Add the hooks by hand, or ask the "
                    f"team. Commands: {start} ; {stop}"
                )
            continue
        if not install and not path.exists():
            continue
        data = _read(path)
        before = json.dumps(data, sort_keys=True)
        data = adapter.add(data) if install else adapter.remove(data)
        if json.dumps(data, sort_keys=True) == before and path.exists():
            continue
        verb = "write" if install else "update"
        if not install and _empty(data):
            verb = "remove"
        steps.append(f"{verb} {path}")
        if dry_run:
            continue
        if verb == "remove":
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
    if install:
        steps += exclude(project, [adapter.rel], dry_run)
    return steps


@dataclass
class StaleHook:
    agent: str  # the adapter name
    rel: str  # the settings file, relative to the checkout
    event: str
    command: str
    tracked: bool


def _commands(node) -> list[str]:
    if isinstance(node, dict):
        found = [node["command"]] if isinstance(node.get("command"), str) else []
        return found + [c for v in node.values() for c in _commands(v)]
    if isinstance(node, list):
        return [c for v in node for c in _commands(v)]
    return []


def stale_hooks(project: Project, pattern: re.Pattern) -> list[StaleHook]:
    """Hook commands in the main checkout's settings files that match `pattern`.

    Files that are not valid JSON are skipped: `memory hooks install` reports them.
    """
    found: list[StaleHook] = []
    for adapter in ADAPTERS.values():
        for rel in (adapter.rel, *adapter.shared):
            try:
                data = _read(project.main_root / rel)
            except BadConfig:
                continue
            hooks = data.get("hooks")
            for event, groups in hooks.items() if isinstance(hooks, dict) else []:
                for command in _commands(groups):
                    if pattern.search(command):
                        found.append(
                            StaleHook(adapter.name, rel, event, command, is_tracked(project, rel))
                        )
    return found


def generic_help() -> str:
    return (
        "Generic agent setup. Connect these commands in your agent tool:\n"
        f"  session start: {hook_command('session-start', 'generic')}\n"
        "      prints the memory and the rules; add the output to the agent's context.\n"
        f"  session stop:  {hook_command('stop', 'generic')}\n"
        "      exits 1 with a message on stderr when the agent must fix or record\n"
        "      something before it finishes; give that message back to the agent.\n"
        "Or add to the agent's instructions: run `memory load` at session start,\n"
        "and `memory check --strict` before you finish."
    )
