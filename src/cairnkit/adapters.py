"""Hook adapters: write each agent tool's local hook config.

Formats follow each tool's public hook docs (checked 2026-10-22, loop
breaker events rechecked 2026-10-30):

- Claude Code: `.claude/settings.local.json`, events `SessionStart`, `Stop`, `PostToolUse`,
  `PostToolUseFailure`, `UserPromptSubmit` and `SubagentStart`. SessionStart stdout is added to
  the context. A Stop hook that prints `{"decision": "block", "reason": ...}` makes the agent
  continue.
- Codex: `.codex/hooks.json`, the same shape with no `PostToolUseFailure`. Stop must print JSON
  on exit 0. Project hooks run only in a trusted project, after review in `/hooks`.
- Cursor: `.cursor/hooks.json` (`version: 1`), events `sessionStart` (JSON `additional_context`),
  `stop` (JSON `followup_message`, capped by `loop_limit`), `afterShellExecution`,
  `postToolUseFailure` and `preCompact`.
- Grok Build: `.grok/hooks/*.json`, the same shape as Claude Code. It reads only `systemMessage`
  from `SessionStart` and discards the stdout of `UserPromptSubmit`, so the memory reaches the
  model at the first tool result, or at the first stop when no tool runs.
- Pi: `.pi/extensions/*.ts`. `before_agent_start` injects a message. A message queued at
  `agent_end` starts no turn, so stop waits until Pi is idle. Print mode has no later turn, so
  its stop arrives at the next `before_agent_start`.
- OpenCode: `.opencode/plugins/*.js`. `client.session.prompt` with `noReply` adds context.

The core never depends on these tools. Only this module names them.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cairnkit.ignore import exclude, is_tracked
from cairnkit.paths import Project

MARK = "cairnkit hook"
# What a hook command held before the rename. Install replaces it; uninstall removes it.
MARKS = (MARK, "project_memory hook")
EXPERIMENTAL = {"codex", "cursor", "grok", "pi", "opencode"}
CODEX_TRUST = "Codex: approve the hooks once with /hooks, because Codex asks for trust itself."


def hook_command(event: str, agent: str) -> str:
    """The command a hook runs. It uses this Python, so PATH does not matter."""
    return f"{shlex.quote(sys.executable)} -m cairnkit hook {event} --agent {agent}"


def holds_ours(path: Path) -> bool:
    """True when the agent file at path holds a memory hook."""
    try:
        return any(mark in path.read_text(encoding="utf-8") for mark in MARKS)
    except (OSError, UnicodeDecodeError):
        return False


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
    """Claude Code, Codex and Grok: hooks -> Event -> [ {matcher, hooks: [handler]} ]."""

    def __init__(
        self,
        name: str,
        rel: str,
        start_matcher: str,
        shared: tuple[str, ...] = (),
        failure_events: tuple[str, ...] = (),
    ):
        super().__init__(name, rel, shared)
        self.start_matcher = start_matcher
        self.failure_events = failure_events

    def _groups(self) -> dict[str, dict]:
        start = {"type": "command", "command": hook_command("session-start", self.name)}
        stop = {"type": "command", "command": hook_command("stop", self.name), "timeout": 30}
        after = {
            "type": "command",
            "command": hook_command("after-shell", self.name),
            "timeout": 5,
        }
        return {
            "SessionStart": {"matcher": self.start_matcher, "hooks": [{**start, "timeout": 10}]},
            "Stop": {"hooks": [stop]},
            # Loop breaker: shell/tool failures. Matcher left open so Bash and
            # similar tools are included; the hook ignores non-command payloads.
            "PostToolUse": {"hooks": [after]},
            "UserPromptSubmit": {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command("prompt", self.name),
                        "timeout": 5,
                    }
                ]
            },
            "SubagentStart": {
                "hooks": [
                    {
                        "type": "command",
                        "command": hook_command("subagent-start", self.name),
                        "timeout": 10,
                    }
                ]
            },
            **{event: {"hooks": [after]} for event in self.failure_events},
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
        hooks.setdefault("afterShellExecution", []).append(
            {"command": hook_command("after-shell", "cursor"), "timeout": 5}
        )
        hooks.setdefault("postToolUseFailure", []).append(
            {"command": hook_command("after-shell", "cursor"), "timeout": 5}
        )
        hooks.setdefault("preCompact", []).append(
            {"command": hook_command("pre-compact", "cursor"), "timeout": 5}
        )
        return data


@dataclass
class FileAdapter(Adapter):
    """A tool that loads code, not settings: the tool owns one generated file."""

    template: str = ""

    def render(self) -> str:
        return (
            self.template.replace("__PYTHON__", json.dumps(sys.executable))
            .replace("__MARK__", MARK)
            .lstrip()
        )


PI_EXTENSION = """
// __MARK__ adapter. Generated by `memory hooks install`. Not shared.
import { execFileSync } from "node:child_process";

const PYTHON = __PYTHON__;

function hook(event: string, payload: object): string {
  try {
    const args = ["-m", "cairnkit", "hook", event, "--agent", "pi"];
    return execFileSync(PYTHON, args, {
      input: JSON.stringify(payload),
      encoding: "utf8",
      timeout: 30000,
      stdio: ["pipe", "pipe", "ignore"],
    }).trim();
  } catch {
    return "";
  }
}

export default function (pi: any) {
  let pending = "";
  let continued = false;
  let waiting: any;
  const key = (ctx: any) => String(ctx.sessionManager.getSessionFile() ?? "pi");
  const say = (content: string, options: object) =>
    pi.sendMessage({ customType: "cairnkit", content, display: false }, options);

  pi.on("session_start", async (event: any, ctx: any) => {
    // `pi -c` says "startup" for a session that already holds messages.
    const held = ctx.sessionManager.getEntries().some((entry: any) => entry.type === "message");
    const source = event.reason === "startup" && held ? "resume" : event.reason;
    pending = hook("session-start", { session_id: key(ctx), source });
  });
  pi.on("session_compact", async (_event: any, ctx: any) => {
    pending = hook("session-start", { session_id: key(ctx), source: "compact" });
  });
  pi.on("before_agent_start", async (_event: any, ctx: any) => {
    continued = false;
    clearTimeout(waiting);
    // Print mode cannot start a turn after a run, so the stop of the last run arrives here.
    const late = ctx.hasUI ? "" : hook("stop", { session_id: key(ctx) });
    const news = hook("prompt", { session_id: key(ctx) });
    const text = [pending, late, news].filter(Boolean).join("\\n\\n");
    pending = "";
    if (!text) return undefined;
    return { message: { customType: "cairnkit", content: text, display: false } };
  });
  pi.on("tool_result", async (event: any, ctx: any) => {
    if (event.toolName !== "bash") return;
    const text = hook("after-shell", {
      session_id: key(ctx),
      hook_event_name: event.isError ? "PostToolUseFailure" : "PostToolUse",
      tool_name: "bash",
      tool_input: { command: event.input?.command },
      tool_response: {},
    });
    if (text) say(text, { deliverAs: "steer" });
  });
  pi.on("agent_end", async (event: any, ctx: any) => {
    clearTimeout(waiting);
    const reason = event.messages?.at(-1)?.stopReason;
    if (continued || !ctx.hasUI || reason === "error" || reason === "aborted") return;
    // A message queued at agent_end starts no turn. The hook marks an event as told, so it runs
    // only when Pi is idle and the message can start one.
    const session = key(ctx);
    const deliver = () => {
      try {
        if (!ctx.isIdle() || ctx.hasPendingMessages()) {
          waiting = setTimeout(deliver, 50);
          return;
        }
        const text = hook("stop", { session_id: session });
        if (text) {
          continued = true;
          say(text, { triggerTurn: true });
        }
      } catch {
        // The session was replaced, so nothing was told.
      }
    };
    waiting = setTimeout(deliver, 0);
  });
}
"""

OPENCODE_PLUGIN = """
// __MARK__ adapter. Generated by `memory hooks install`. Not shared.
import { spawnSync } from "node:child_process";

const PYTHON = __PYTHON__;

function hook(event, payload, cwd) {
  const args = ["-m", "cairnkit", "hook", event, "--agent", "opencode"];
  const result = spawnSync(PYTHON, args, {
    input: JSON.stringify(payload),
    encoding: "utf8",
    timeout: 30000,
    cwd,
  });
  return result.status === 0 ? (result.stdout || "").trim() : "";
}

export const CairnkitMemory = async ({ client, directory }) => {
  const continued = new Set();
  const say = (id, text, noReply) =>
    client.session.prompt({
      path: { id },
      body: { noReply, parts: [{ type: "text", text }] },
    });
  const load = async (id, source) => {
    const text = hook("session-start", { session_id: id, source }, directory);
    if (text) await say(id, text, true);
  };
  return {
    event: async ({ event }) => {
      const id = event.properties?.sessionID ?? event.properties?.info?.id;
      if (!id) return;
      if (event.type === "session.created") await load(id, "startup");
      if (event.type === "session.compacted") await load(id, "compact");
      if (event.type === "session.idle") {
        if (continued.delete(id)) return;
        const text = hook("stop", { session_id: id }, directory);
        if (text) {
          continued.add(id);
          await say(id, text, false);
        }
      }
    },
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "bash") return;
      const exit = output?.metadata?.exit;
      if (typeof exit !== "number") return;
      const text = hook(
        "after-shell",
        {
          session_id: input.sessionID,
          hook_event_name: exit === 0 ? "PostToolUse" : "PostToolUseFailure",
          tool_name: "bash",
          tool_input: { command: input.args?.command },
          tool_response: {},
        },
        directory,
      );
      if (text) await say(input.sessionID, text, true);
    },
  };
};
"""


ADAPTERS: dict[str, Adapter] = {
    "claude": NestedAdapter(
        "claude",
        ".claude/settings.local.json",
        "startup|resume|clear|compact",
        shared=(".claude/settings.json",),
        failure_events=("PostToolUseFailure",),
    ),
    "codex": NestedAdapter("codex", ".codex/hooks.json", "startup|resume|clear|compact"),
    "cursor": CursorAdapter("cursor", ".cursor/hooks.json"),
    # Grok Build also runs a project's Claude Code and Cursor hooks. See detect().
    "grok": NestedAdapter(
        "grok",
        ".grok/hooks/cairnkit.json",
        "startup|resume|clear|compact",
        failure_events=("PostToolUseFailure",),
    ),
    "pi": FileAdapter("pi", ".pi/extensions/cairnkit.ts", template=PI_EXTENSION),
    "opencode": FileAdapter("opencode", ".opencode/plugins/cairnkit.js", template=OPENCODE_PLUGIN),
}
BINARIES = {
    "claude": "claude",
    "codex": "codex",
    "cursor": "cursor-agent",
    "grok": "grok",
    "pi": "pi",
    "opencode": "opencode",
}


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
    if "grok" in found and {"claude", "cursor"} & set(found):
        found.remove("grok")  # Grok runs those hooks too, and each hook must run once.
    return found or ["generic"]


def codex_in_use() -> bool:
    """True when Codex ever wrote a session. A program on PATH or a home folder is not use.

    Codex keeps each session as `sessions/YYYY/MM/DD/rollout-*.jsonl` under `CODEX_HOME`.
    Other files there, such as its logs, change while nobody runs a session.
    """
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        return any(any(day.iterdir()) for day in (home / "sessions").glob("[0-9]*/[0-9]*/[0-9]*"))
    except OSError:
        return False


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


def _apply_file(
    project: Project, adapter: FileAdapter, install: bool, dry_run: bool, checkouts
) -> list[str]:
    steps: list[str] = []
    if is_tracked(project, adapter.rel):
        return [f"skip {adapter.rel}: it is tracked by git. The tool writes no tracked file."]
    text = adapter.render()
    for checkout in project.checkouts if checkouts is None else checkouts:
        path = checkout / adapter.rel
        if install:
            if path.exists() and MARK not in path.read_text(encoding="utf-8"):
                steps.append(f"skip {path}: the file is not ours")
                continue
            if path.exists() and path.read_text(encoding="utf-8") == text:
                continue
            steps.append(f"write {path}")
            if not dry_run:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        elif path.exists() and MARK in path.read_text(encoding="utf-8"):
            steps.append(f"remove {path}")
            if not dry_run:
                path.unlink()
    if install:
        steps += exclude(project, [adapter.rel], dry_run)
    return steps


def apply(
    project: Project, name: str, install: bool, dry_run: bool, checkouts: list[Path] | None = None
) -> list[str]:
    """Install or remove one adapter in every checkout, or in `checkouts`. Return the steps."""
    adapter = ADAPTERS[name]
    if isinstance(adapter, FileAdapter):
        return _apply_file(project, adapter, install, dry_run, checkouts)
    steps: list[str] = []
    tracked = is_tracked(project, adapter.rel)
    for checkout in project.checkouts if checkouts is None else checkouts:
        path = checkout / adapter.rel
        if tracked:
            if install:
                commands = " ; ".join(dict.fromkeys(_commands(adapter.add({}))))
                steps.append(
                    f"skip {path}: it is tracked by git. The tool writes no tracked file. "
                    f"Add the hooks by hand in a file that git ignores. Commands: {commands}"
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
    if install and not tracked:
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


def stale_hooks(project: Project, matches: Callable[[str], object]) -> list[StaleHook]:
    """Hook commands in this checkout's settings files that `matches` accepts.

    Files that are not valid JSON are skipped: `memory hooks install` reports them.
    """
    found: list[StaleHook] = []
    for adapter in ADAPTERS.values():
        if isinstance(adapter, FileAdapter):
            continue
        for rel in (adapter.rel, *adapter.shared):
            try:
                data = _read(project.root / rel)
            except BadConfig:
                continue
            hooks = data.get("hooks")
            for event, groups in hooks.items() if isinstance(hooks, dict) else []:
                for command in _commands(groups):
                    if matches(command):
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
        "and `memory check --strict` before you finish.\n"
        "This adapter cannot see a failed command. If a failure was recorded, stop still says "
        "to stop retrying, find the cause, search the memory (`memory search WORDS`), or ask."
    )
