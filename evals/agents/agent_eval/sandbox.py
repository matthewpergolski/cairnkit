"""The tool builds and the throwaway repos they run in. Nothing here touches a real memory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_eval.agents import Agent
from agent_eval.scoring import NO_MEMORY

PROD_REF = "d523c01"
MEMORY_LINK = "memory-bank"
STRIPPED_ENV = (
    "CLAUDECODE",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
    "CODEX_CI",
    "CODEX_SANDBOX",
    "CODEX_THREAD_ID",
    "CURSOR_AGENT",
    "CURSOR_TRACE_ID",
    "OPENCODE",
    "OPENCODE_SESSION_ID",
    "PI_CODING_AGENT",
    "GROK_SESSION_ID",
    "GROK_HOOK_EVENT",
    "GROK_WORKSPACE_ROOT",
    "MEMORY_DIR",
    "MEMORY_WRITER",
    "VIRTUAL_ENV",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
)
STRIPPED_PREFIXES = ("CLAUDE_CODE_",)
PROVIDER_ENV_PREFIXES = ("ANTHROPIC_", "OPENAI_", "XAI_", "CURSOR_", "OPENCODE_", "GEMINI_")

TRACE_MODULE = """\
import json, os, sys, time

def _trace():
    if os.environ.get("CAIRNKIT_EVAL_HARNESS"):
        return
    argv = list(getattr(sys, "orig_argv", sys.argv))
    text = " ".join(argv)
    if "cairnkit" not in text and "/memory" not in text:
        return
    line = json.dumps({"argv": argv[1:], "cwd": os.getcwd(), "at": time.time()})
    fd = os.open(__TRACE__, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, (line + "\\n").encode())
    finally:
        os.close(fd)

try:
    _trace()
except Exception:
    pass
"""


class SetupError(RuntimeError):
    """The kit could not build or seed. This is never a result about cairnkit or the agent."""


def run(
    argv: list[str],
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: float = 120,
    check: bool = True,
) -> subprocess.CompletedProcess:
    try:
        done = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"{argv[0]}: {exc}") from exc
    if check and done.returncode != 0:
        tail = (done.stderr or done.stdout)[-400:]
        raise SetupError(f"{' '.join(argv[:3])} exited {done.returncode}: {tail}")
    return done


def _strip_env(base: dict) -> dict:
    env = {k: v for k, v in base.items() if k not in STRIPPED_ENV}
    return {k: v for k, v in env.items() if not k.startswith(STRIPPED_PREFIXES)}


@dataclass(frozen=True)
class Build:
    label: str
    commit: str
    root: Path
    version: str
    has_memory: bool = True

    @property
    def bin_dir(self) -> Path:
        return self.root / "venv" / "bin"

    @property
    def memory(self) -> Path:
        return self.bin_dir / "memory"

    @property
    def trace_path(self) -> Path:
        return self.root / "trace.jsonl"

    def read_trace(self, under: Path) -> list[dict]:
        """Each run of this build's Python whose folder is under `under`."""
        if not self.trace_path.exists():
            return []
        rows = []
        prefix = str(under.resolve())
        for line in self.trace_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if str(row.get("cwd", "")).startswith(prefix):
                rows.append(row)
        return rows


def resolve_commit(repo: Path, ref: str) -> str:
    return run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=repo).stdout.strip()


def make_build(label: str, ref: str, repo: Path, builds_dir: Path) -> Build:
    """Export `ref` and install it in its own venv. A second call reuses the result."""
    commit = resolve_commit(repo, ref)
    kit = hashlib.sha256(TRACE_MODULE.encode()).hexdigest()[:6]
    root = (builds_dir / f"{label}-{commit[:12]}-{kit}").resolve()
    env = _strip_env(os.environ.copy())
    env["UV_NO_PROGRESS"] = "1"
    marker = root / "built.json"
    if not marker.exists():
        shutil.rmtree(root, ignore_errors=True)
        source = root / "source"
        source.mkdir(parents=True)
        archive = root / "source.tar"
        run(["git", "archive", "--format=tar", "-o", str(archive), commit], cwd=repo)
        with tarfile.open(archive) as handle:
            handle.extractall(source, filter="data")
        venv = root / "venv"
        run(["uv", "venv", "--python", "3.12", "--no-project", str(venv)], cwd=root, env=env)
        run(
            ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), str(source)],
            cwd=root,
            env=env,
            timeout=300,
        )
        _install_trace(venv, root / "trace.jsonl")
        version = run([str(venv / "bin" / "memory"), "--version"], cwd=root, env=env).stdout
        marker.write_text(json.dumps({"commit": commit, "version": version.strip()}))
    version = json.loads(marker.read_text())["version"]
    return Build(label=label, commit=commit, root=root, version=version)


def no_memory_build(builds_dir: Path) -> Build:
    """The arm with no tool: nothing to install, and a trace that stays empty."""
    root = (builds_dir / NO_MEMORY).resolve()
    return Build(label=NO_MEMORY, commit=NO_MEMORY, root=root, version="none", has_memory=False)


def _install_trace(venv: Path, trace_path: Path) -> None:
    """Log each start of the tool, with no change to its source, in both builds alike."""
    sites = list((venv / "lib").glob("python*/site-packages"))
    if len(sites) != 1:
        raise SetupError(f"expected one site-packages folder, found {len(sites)}")
    module = TRACE_MODULE.replace("__TRACE__", json.dumps(str(trace_path)))
    (sites[0] / "cairnkit_eval_trace.py").write_text(module, encoding="utf-8")
    (sites[0] / "cairnkit_eval_trace.pth").write_text("import cairnkit_eval_trace\n")


def seed_record(fact, now: datetime) -> dict:
    when = now - timedelta(days=fact.age_days)
    digest = hashlib.sha256(fact.text.encode()).hexdigest()[:4]
    record = {
        "type": "fact",
        "id": f"f-{when:%Y%m%d}-{digest}",
        "kind": fact.kind,
        "text": fact.text,
        "area": fact.area,
        "happened_at": when.date().isoformat(),
        "learned_at": when.replace(microsecond=0).isoformat(),
        "source": f"session:{when.date().isoformat()}",
        "basis": "seen",
        "status": "active",
        "writer": "seed",
    }
    if fact.pinned:
        record["pinned"] = True
    return record


@dataclass
class Sandbox:
    build: Build
    agent: Agent
    root: Path
    repo: Path
    memory_dir: Path
    home: Path
    env: dict = field(default_factory=dict)
    setup_env: dict = field(default_factory=dict)
    connect_steps: list[dict] = field(default_factory=list)
    seed_ids: dict[str, str] = field(default_factory=dict)
    git_after_connect: list[str] = field(default_factory=list)
    git_before_agent: list[str] = field(default_factory=list)
    head_after_setup: str = ""

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return run(["git", *args], cwd=cwd or self.repo, env=self.setup_env).stdout

    def memory_cmd(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return run(
            [str(self.build.memory), *args],
            cwd=cwd or self.repo,
            env=self.setup_env,
            check=False,
        )

    def git_status(self) -> list[str]:
        return [line for line in self.git("status", "--porcelain").splitlines() if line]

    def read_records(self) -> list[dict]:
        rows = []
        for path in sorted((self.memory_dir / "facts").glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
        return rows


def _setup_path(build: Build, agent: Agent, shim: Path) -> str:
    """One agent on PATH, so that detection in the tool connects that agent and no other."""
    shim.mkdir(parents=True, exist_ok=True)
    found = shutil.which(agent.binary)
    if found:
        link = shim / agent.binary
        if not link.exists():
            link.symlink_to(found)
    return os.pathsep.join([str(build.bin_dir), str(shim), "/usr/bin", "/bin"])


def path_without_memory(path: str, shim: Path) -> str:
    """PATH with no `memory` and no `cairnkit`. The other tools of such a folder stay in `shim`.

    A real install often shares a folder with the agent tools, so the folder cannot just go.
    """
    hidden = ("memory", "cairnkit")
    shim.mkdir(parents=True, exist_ok=True)
    kept = []
    for entry in path.split(os.pathsep):
        folder = Path(entry)
        if not any((folder / name).exists() for name in hidden):
            kept.append(entry)
            continue
        for item in folder.iterdir():
            link = shim / item.name
            if item.name not in hidden and not link.exists():
                link.symlink_to(item)
    return os.pathsep.join([str(shim), *kept])


def make_sandbox(
    build: Build,
    agent: Agent,
    scenario,
    root: Path,
    *,
    isolated_home: bool,
    now: datetime | None = None,
) -> Sandbox:
    """A new repo, connected as the docs of this build say, seeded with this scenario's facts."""
    now = now or datetime.now(UTC).astimezone()
    root = root.resolve()
    repo = root / "proj"
    repo.mkdir(parents=True)
    home = root / "home"
    home.mkdir()
    cache = root / "cache"
    git_config = root / "gitconfig"
    git_config.write_text("")

    common = _strip_env(os.environ.copy())
    if isolated_home:
        common = {k: v for k, v in common.items() if not k.startswith(PROVIDER_ENV_PREFIXES)}
    common.update(
        XDG_CACHE_HOME=str(cache),
        GIT_CONFIG_GLOBAL=str(git_config),
        GIT_CONFIG_NOSYSTEM="1",
    )
    if isolated_home:
        common["HOME"] = str(home)

    setup_env = {
        **common,
        "HOME": str(home),
        "CAIRNKIT_EVAL_HARNESS": "1",
        "PATH": _setup_path(build, agent, root / "shim"),
    }
    host_path = os.environ.get("PATH", "")
    agent_env = {
        **common,
        "PATH": os.pathsep.join([str(build.bin_dir), host_path])
        if build.has_memory
        else path_without_memory(host_path, root / "tools"),
    }
    box = Sandbox(
        build=build,
        agent=agent,
        root=root,
        repo=repo,
        memory_dir=root / "proj.memory",
        home=home,
        env=agent_env,
        setup_env=setup_env,
    )
    box.git("init", "-q", "-b", "main")
    box.git("config", "user.name", "eval")
    box.git("config", "user.email", "eval@example.invalid")
    for rel, text in scenario.files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    box.git("add", "-A")
    box.git("commit", "-q", "-m", "start")
    if build.has_memory:
        connect(box)
        config = box.memory_dir / "config.toml"
        config.open("a", encoding="utf-8").write("\nskills_check = false\n")
        write_seed(box, scenario, now)
    box.git_after_connect = box.git_status()
    if scenario.prepare:
        scenario.prepare(box)
    box.git_before_agent = box.git_status()
    box.head_after_setup = box.git("rev-parse", "HEAD").strip()
    return box


def connect(box: Sandbox) -> None:
    """The steps a person runs from the docs. A step that the build lacks is recorded."""
    if _connect_step(box, "init") != 0:
        raise SetupError(f"memory init failed: {box.connect_steps[0]['output']}")
    if _connect_step(box, "hooks", "install", "--agent", box.agent.hook_agent) != 0:
        _connect_step(box, "instructions", "--write-instructions")


def _connect_step(box: Sandbox, *step: str) -> int:
    done = box.memory_cmd(*step)
    output = (done.stdout + done.stderr)[-200:]
    box.connect_steps.append({"step": " ".join(step), "exit": done.returncode, "output": output})
    return done.returncode


def write_seed(box: Sandbox, scenario, now: datetime) -> None:
    lines = []
    for fact in scenario.facts:
        record = seed_record(fact, now)
        box.seed_ids[fact.text] = record["id"]
        lines.append(json.dumps(record, separators=(",", ":"), ensure_ascii=False))
    if lines:
        path = box.memory_dir / "facts" / "seed.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
