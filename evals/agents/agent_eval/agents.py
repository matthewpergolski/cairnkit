"""What the kit knows about each agent tool: its headless command, output format and fake path.

Each flag comes from the tool's `--help`. The kit never passes a flag that skips a safety or a
trust step. `FORBIDDEN_FLAGS` names them, and a test checks each command against the list.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

FORBIDDEN_FLAGS = frozenset(
    {
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "--dangerously-bypass-approvals-and-sandbox",
        "--dangerously-bypass-hook-trust",
        "--approve-for-me",
        "--trust",
        "--force",
        "-f",
        "--yolo",
        "--approve-mcps",
        "--auto",
        "--always-approve",
        "--bare",
        "--safe-mode",
        "--pure",
        "--no-extensions",
        "-ne",
        "--no-context-files",
        "-nc",
    }
)
FORBIDDEN_VALUES = frozenset({"bypassPermissions", "danger-full-access"})


@dataclass
class Parsed:
    """The parts of a tool's stdout that the scoring reads. The text is data, never code."""

    text: str = ""
    model: str | None = None
    is_error: bool = False
    error_text: str = ""
    tool_names: list[str] = field(default_factory=list)
    subagents: int | None = None
    retry_error: str = ""


@dataclass
class CallContext:
    prompt: str
    repo: Path
    memory_dir: Path | None
    model: str | None
    resume: bool = False
    budget_usd: float | None = None


@dataclass
class FakeSetup:
    """Temp config for one run against the fake provider. Only env and files in the temp dir."""

    env: dict[str, str]
    model: str


def _json_lines(stdout: str) -> list[dict]:
    rows = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _whole_json(stdout: str) -> list[dict]:
    rows = _json_lines(stdout)
    if rows:
        return rows
    try:
        row = json.loads(stdout)
    except ValueError:
        return []
    return [row] if isinstance(row, dict) else []


def parse_claude(stdout: str) -> Parsed:
    out = Parsed()
    for row in _whole_json(stdout):
        kind = row.get("type")
        if kind == "system" and row.get("subtype") == "api_retry":
            out.retry_error = f"{row.get('error_status')} {row.get('error')}"
        elif kind == "assistant":
            message = row.get("message") or {}
            out.model = message.get("model") or out.model
            for block in message.get("content") or []:
                if block.get("type") == "tool_use":
                    out.tool_names.append(str(block.get("name")))
                elif block.get("type") == "text":
                    out.text = str(block.get("text") or "") or out.text
        elif kind == "result":
            out.text = str(row.get("result") or "") or out.text
            out.is_error = bool(row.get("is_error"))
            usage = row.get("modelUsage")
            if isinstance(usage, dict) and usage:
                out.model = next(iter(usage))
            stats = row.get("subagent_stats")
            if isinstance(stats, dict):
                out.subagents = int(stats.get("spawned") or 0)
            if out.is_error:
                errors = row.get("errors") or []
                out.error_text = " ".join(map(str, errors)) or str(row.get("result") or "")
    return out


def parse_codex(stdout: str) -> Parsed:
    out = Parsed()
    for row in _json_lines(stdout):
        kind = row.get("type")
        item = row.get("item") or {}
        if kind == "item.completed" and item.get("type") == "agent_message":
            out.text = str(item.get("text") or "") or out.text
        elif kind == "item.completed" and item.get("type") in (
            "collab_tool_call",
            "command_execution",
            "mcp_tool_call",
        ):
            out.tool_names.append(str(item.get("tool") or item.get("type")))
        elif kind in ("error", "turn.failed"):
            out.is_error = True
            error = row.get("error") or {}
            detail = error.get("message") if isinstance(error, dict) else error
            out.error_text = str(row.get("message") or detail or "")
    return out


def parse_cursor(stdout: str) -> Parsed:
    out = Parsed()
    for row in _whole_json(stdout):
        kind = row.get("type")
        if kind == "assistant":
            for block in (row.get("message") or {}).get("content") or []:
                if block.get("type") == "text":
                    out.text = str(block.get("text") or "") or out.text
        elif kind == "tool_call":
            out.tool_names.extend(str(name) for name in (row.get("tool_call") or {}))
        elif kind == "result":
            out.text = str(row.get("result") or "") or out.text
            out.is_error = bool(row.get("is_error"))
            if out.is_error:
                out.error_text = str(row.get("result") or "")
        elif kind == "system":
            out.model = row.get("model") or out.model
    return out


def parse_opencode(stdout: str) -> Parsed:
    out = Parsed()
    chunks: list[str] = []
    for row in _json_lines(stdout):
        kind = row.get("type")
        part = row.get("part") or {}
        if kind == "text":
            chunks.append(str(part.get("text") or ""))
        elif kind == "tool_use":
            out.tool_names.append(str(part.get("tool")))
        elif kind == "error":
            out.is_error = True
            error = row.get("error") or {}
            data = error.get("data") if isinstance(error, dict) else None
            detail = data.get("message") if isinstance(data, dict) else None
            out.error_text = str(detail or error)
    out.text = chunks[-1] if chunks else ""
    return out


def parse_pi(stdout: str) -> Parsed:
    out = Parsed()
    for row in _json_lines(stdout):
        kind = row.get("type")
        if kind == "turn_end":
            message = row.get("message") or {}
            out.model = message.get("model") or out.model
            if message.get("stopReason") == "error":
                out.is_error = True
                out.error_text = str(message.get("errorMessage") or "")
            for block in message.get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    out.text = str(block["text"])
                elif block.get("type") == "toolCall":
                    out.tool_names.append(str(block.get("name")))
    return out


def parse_grok(stdout: str) -> Parsed:
    out = Parsed()
    for row in _whole_json(stdout):
        kind = row.get("type")
        if kind == "error":
            out.is_error = True
            out.error_text = str(row.get("message") or "")
        elif kind == "result" or "result" in row or "text" in row:
            out.text = str(row.get("result") or row.get("text") or "") or out.text
            out.model = row.get("model") or out.model
            if row.get("is_error"):
                out.is_error = True
                out.error_text = out.text
    if not out.text and not out.is_error and not _whole_json(stdout):
        out.text = stdout.strip()
    return out


CLAUDE_TOOLS = ",".join(
    [
        "Read",
        "Edit",
        "Write",
        "Grep",
        "Glob",
        "Task",
        "Agent",
        "Bash(memory *)",
        "Bash(cairnkit *)",
        "Bash(git *)",
        "Bash(sh *)",
        "Bash(ls *)",
        "Bash(cat *)",
        "Bash(make *)",
        "Bash(env *)",
        "Bash(export *)",
        "Bash(REPORT_LOCALE=*)",
    ]
)


def _add_dir(call: CallContext) -> list[str]:
    return ["--add-dir", str(call.memory_dir)] if call.memory_dir else []


def claude_argv(call: CallContext) -> list[str]:
    argv = [
        "claude",
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-hook-events",
        "--setting-sources",
        "project,local",
        "--strict-mcp-config",
        "--allowedTools",
        CLAUDE_TOOLS,
        *_add_dir(call),
    ]
    if call.model:
        argv += ["--model", call.model]
    if call.budget_usd is not None:
        argv += ["--max-budget-usd", f"{call.budget_usd:.2f}"]
    if call.resume:
        argv.append("--continue")
    return [*argv, "--", call.prompt]


def claude_live_argv(call: CallContext) -> list[str]:
    """One process for all turns, so that a restart cannot hide a mid-session change."""
    return [*claude_argv(call)[:-2], "--input-format", "stream-json"]


def live_message(prompt: str) -> str:
    message = {"role": "user", "content": prompt}
    return json.dumps({"type": "user", "message": message}) + "\n"


def codex_argv(call: CallContext) -> list[str]:
    argv = ["codex", "exec"]
    if call.resume:
        argv += ["resume", "--last"]
    else:
        argv += ["-s", "workspace-write", *_add_dir(call), "-C", str(call.repo)]
    argv.append("--json")
    if call.model:
        argv += ["-m", call.model]
    return [*argv, call.prompt]


def cursor_argv(call: CallContext) -> list[str]:
    argv = [
        "cursor-agent",
        "-p",
        "--output-format",
        "stream-json",
        "--workspace",
        str(call.repo),
        *_add_dir(call),
    ]
    if call.model:
        argv += ["--model", call.model]
    if call.resume:
        argv.append("--continue")
    return [*argv, call.prompt]


def opencode_argv(call: CallContext) -> list[str]:
    argv = ["opencode", "run", "--format", "json", "--dir", str(call.repo)]
    if call.model:
        argv += ["-m", call.model]
    if call.resume:
        argv.append("--continue")
    return [*argv, call.prompt]


def pi_argv(call: CallContext) -> list[str]:
    argv = ["pi", "-p", "--mode", "json", "--offline"]
    if call.model:
        argv += ["--model", call.model]
    if call.resume:
        argv.append("--continue")
    return [*argv, call.prompt]


def grok_argv(call: CallContext) -> list[str]:
    argv = ["grok", "--output-format", "streaming-messages-json", "--cwd", str(call.repo)]
    for rule in ("Bash(memory *)", "Bash(git *)", "Bash(sh *)"):
        argv += ["--allow", rule]
    if call.model:
        argv += ["-m", call.model]
    if call.resume:
        argv.append("--continue")
    return [*argv, "-p", call.prompt]


def fake_pi(temp: Path, url: str) -> FakeSetup:
    folder = temp / "pi"
    folder.mkdir()
    provider = {
        "baseUrl": f"{url}/v1",
        "api": "openai-completions",
        "apiKey": "fake",
        "models": [{"id": "fake-small"}],
    }
    (folder / "models.json").write_text(json.dumps({"providers": {"fake": provider}}))
    env = {"PI_CODING_AGENT_DIR": str(folder), "PI_OFFLINE": "1"}
    return FakeSetup(env, "fake/fake-small")


def fake_opencode(temp: Path, url: str) -> FakeSetup:
    provider = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "fake",
        "options": {"baseURL": f"{url}/v1", "apiKey": "fake"},
        "models": {"fake-small": {"name": "fake-small"}},
    }
    config = {"autoupdate": False, "share": "disabled", "provider": {"fake": provider}}
    path = temp / "opencode.json"
    path.write_text(json.dumps(config))
    env = {
        "OPENCODE_CONFIG": str(path),
        "XDG_CONFIG_HOME": str(temp / "xdg-config"),
        "XDG_DATA_HOME": str(temp / "xdg-data"),
        "XDG_STATE_HOME": str(temp / "xdg-state"),
    }
    return FakeSetup(env, "fake/fake-small")


def fake_codex(temp: Path, url: str) -> FakeSetup:
    folder = temp / "codex"
    folder.mkdir()
    (folder / "config.toml").write_text(
        'model = "fake-small"\n'
        'model_provider = "fake"\n'
        "[model_providers.fake]\n"
        'name = "fake"\n'
        f'base_url = "{url}/v1"\n'
        'env_key = "FAKE_PROVIDER_KEY"\n'
        'wire_api = "responses"\n'
    )
    return FakeSetup({"CODEX_HOME": str(folder), "FAKE_PROVIDER_KEY": "fake"}, "fake-small")


def fake_claude(temp: Path, url: str) -> FakeSetup:
    env = {
        "CLAUDE_CONFIG_DIR": str(temp / "claude"),
        "ANTHROPIC_BASE_URL": url,
        "ANTHROPIC_API_KEY": "sk-fake",
    }
    return FakeSetup(env, "fake-small")


def fake_grok(temp: Path, url: str) -> FakeSetup:
    folder = temp / "grok"
    folder.mkdir()
    (folder / "config.toml").write_text(
        "[features]\n"
        "remote_fetch = false\n"
        "[model.fake-small]\n"
        'model = "fake-small"\n'
        f'base_url = "{url}/v1"\n'
        'name = "fake"\n'
        'api_key = "fake"\n'
        'api_backend = "chat_completions"\n'
    )
    return FakeSetup({"GROK_HOME": str(folder), "XAI_API_KEY": "fake"}, "fake-small")


@dataclass(frozen=True)
class Agent:
    name: str
    binary: str
    default_model: str
    argv: Callable[[CallContext], list[str]]
    parse: Callable[[str], Parsed]
    hook_agent: str
    version_args: tuple[str, ...] = ("--version",)
    capabilities: frozenset[str] = frozenset({"resume"})
    live_argv: Callable[[CallContext], list[str]] | None = None
    fake: Callable[[Path, str], FakeSetup] | None = None
    no_fake_reason: str = ""
    connect_note: str = ""


AGENTS: dict[str, Agent] = {
    agent.name: agent
    for agent in (
        Agent(
            name="claude",
            binary="claude",
            default_model="haiku",
            argv=claude_argv,
            parse=parse_claude,
            hook_agent="claude",
            capabilities=frozenset({"resume", "subagent", "compact"}),
            live_argv=claude_live_argv,
            fake=fake_claude,
        ),
        Agent(
            name="codex",
            binary="codex",
            default_model="gpt-6-luna",
            argv=codex_argv,
            parse=parse_codex,
            hook_agent="codex",
            capabilities=frozenset({"resume", "subagent"}),
            fake=fake_codex,
            connect_note="Project hooks need a trust review in /hooks. The kit does not skip it.",
        ),
        Agent(
            name="cursor-agent",
            binary="cursor-agent",
            default_model="auto",
            argv=cursor_argv,
            parse=parse_cursor,
            hook_agent="cursor",
            capabilities=frozenset({"resume", "subagent"}),
            no_fake_reason="It uses a private protocol and an account key exchange.",
            connect_note="Headless mode needs a workspace trust step. The kit does not skip it.",
        ),
        Agent(
            name="opencode",
            binary="opencode",
            default_model="openai/gpt-5.4-mini",
            argv=opencode_argv,
            parse=parse_opencode,
            hook_agent="opencode",
            capabilities=frozenset({"resume", "subagent"}),
            fake=fake_opencode,
        ),
        Agent(
            name="pi",
            binary="pi",
            default_model="openai-codex/gpt-5.4-mini",
            argv=pi_argv,
            parse=parse_pi,
            hook_agent="pi",
            capabilities=frozenset({"resume"}),
            fake=fake_pi,
        ),
        Agent(
            name="grok",
            binary="grok",
            default_model="grok-4.7-build-fast",
            argv=grok_argv,
            parse=parse_grok,
            hook_agent="grok",
            capabilities=frozenset({"resume", "subagent"}),
            fake=fake_grok,
            connect_note="Project hooks need folder trust. The kit does not skip it.",
        ),
    )
}


def forbidden_in(argv: list[str]) -> list[str]:
    """Any flag or value in a command that would skip a safety or a trust step."""
    return [word for word in argv if word in FORBIDDEN_FLAGS or word in FORBIDDEN_VALUES]


def version_of(text: str) -> str:
    line = next((line for line in text.splitlines() if line.strip()), "")
    return re.sub(r"\s+", " ", line).strip()[:80]
