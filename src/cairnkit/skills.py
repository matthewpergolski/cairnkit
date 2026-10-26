"""pstack skills: `memory skills status|install`, and the one advisory line.

Everything is at user level. Nothing is written into a repo. The check never
fails and never blocks: offline or on any error, it says nothing.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from cairnkit.clock import now, parse_time, stamp
from cairnkit.config import load_config

REPO = "cursor/plugins"
REPO_URL = "https://github.com/cursor/plugins"
PLUGIN_URL = "https://raw.githubusercontent.com/cursor/plugins/main/pstack/plugin.json"
MARKETPLACE = "cursor-plugins"
PLUGIN = f"pstack@{MARKETPLACE}"
COMMAND = "memory skills install pstack --yes"
TOOLS = {"claude": "Claude Code", "codex": "Codex", "cursor": "Cursor"}
FRESH = timedelta(days=1)
FRESH_AFTER_FAILURE = timedelta(hours=1)
MARKER_DIR = ".pstack"
MARKER = "install.json"


# --- the machine: all stubbed in tests ------------------------------------------------


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "cairnkit"})
    with urllib.request.urlopen(request, timeout=3) as reply:
        return reply.read().decode("utf-8")


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(argv: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else Path.home() / ".cache") / "cairnkit"


def checkout() -> tuple[Path, str]:
    """A checkout of cursor/plugins main in the user cache. Return (folder, commit)."""
    folder = cache_dir() / "cursor-plugins"
    if (folder / ".git").is_dir():
        steps = [
            ["git", "-C", str(folder), "fetch", "--depth", "1", "origin", "main"],
            ["git", "-C", str(folder), "reset", "--hard", "FETCH_HEAD"],
        ]
    else:
        folder.parent.mkdir(parents=True, exist_ok=True)
        steps = [["git", "clone", "--depth", "1", REPO_URL, str(folder)]]
    for argv in steps:
        code, out = _run(argv, 300)
        if code:
            raise OSError(out or f"{' '.join(argv)} failed")
    code, out = _run(["git", "-C", str(folder), "rev-parse", "HEAD"])
    if code:
        raise OSError(out)
    return folder, out.strip()


# --- versions -------------------------------------------------------------------------


def _key(version: object) -> tuple[int, ...] | None:
    if isinstance(version, str) and re.fullmatch(r"\d+(\.\d+)*", version):
        return tuple(int(part) for part in version.split("."))
    return None


def is_behind(installed: str | None, latest: str | None) -> bool:
    a, b = _key(installed), _key(latest)
    return a is not None and b is not None and a < b


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def latest_version(force: bool = False) -> str | None:
    """The version in pstack/plugin.json on cursor/plugins main. Cached for a day. Never raises."""
    path = cache_dir() / "pstack-latest.json"
    cached = _read_json(path) or {}
    old = cached.get("version") if _key(cached.get("version")) else None
    moment = now()
    with contextlib.suppress(Exception):
        age = moment - parse_time(str(cached["checked"]))
        limit = FRESH_AFTER_FAILURE if cached.get("failed") else FRESH
        if not force and timedelta(0) <= age < limit:
            return old
    version = None
    with contextlib.suppress(Exception):
        found = json.loads(fetch_text(PLUGIN_URL)).get("version")
        version = found if _key(found) else None
    record = {"checked": stamp(moment), "version": version or old}
    if not version:
        record["failed"] = True
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return version or old


# --- what is installed ----------------------------------------------------------------


def skills_dir(tool: str) -> Path:
    return Path.home() / f".{tool}" / "skills"


def detected(tool: str) -> bool:
    return (Path.home() / f".{tool}").is_dir()


def _marker(tool: str) -> dict:
    return _read_json(skills_dir(tool) / MARKER_DIR / MARKER) or {}


def installed_version(tool: str) -> str | None:
    """The installed pstack version for a tool, or None."""
    if tool != "claude":
        version = _marker(tool).get("version")
        return version if isinstance(version, str) else None
    data = _read_json(Path.home() / ".claude" / "plugins" / "installed_plugins.json") or {}
    entries = (data.get("plugins") or {}).get(PLUGIN) or []
    entries = sorted(
        (e for e in entries if isinstance(e, dict)), key=lambda e: e.get("scope") != "user"
    )
    for entry in entries:
        where = Path(str(entry.get("installPath", "")))
        for name in (where / "plugin.json", where / ".claude-plugin" / "plugin.json"):
            version = (_read_json(name) or {}).get("version")
            if isinstance(version, str):
                return version
        if isinstance(entry.get("version"), str):
            return entry["version"]
    return None


def _marketplace_known() -> bool:
    data = _read_json(Path.home() / ".claude" / "plugins" / "known_marketplaces.json") or {}
    return MARKETPLACE in data


@dataclass
class Row:
    tool: str
    found: bool
    installed: str | None

    @property
    def label(self) -> str:
        return TOOLS[self.tool]

    def state(self, latest: str | None) -> str:
        """not found, missing, behind or current."""
        if not self.found:
            return "not found"
        if self.installed is None:
            return "missing"
        return "behind" if is_behind(self.installed, latest) else "current"


def rows() -> list[Row]:
    return [Row(t, detected(t), installed_version(t)) for t in TOOLS]


MARKERS = {
    "claude": ("CLAUDECODE",),
    "codex": ("CODEX_CI", "CODEX_SANDBOX", "CODEX_THREAD_ID"),
    "cursor": ("CURSOR_AGENT", "CURSOR_TRACE_ID"),
}
STATE_NAME = ".skills-advisory.json"
SHOWN_MAX = 3


def running_tool(agent: str | None = None) -> str | None:
    """The agent tool that runs this session, or None when it is not known.

    The hook's `--agent` wins. Else one set of environment markers must match.
    """
    if agent in TOOLS:
        return agent
    found = [t for t, names in MARKERS.items() if any(os.environ.get(n) for n in names)]
    return found[0] if len(found) == 1 else None


def advisory(tools: list[str] | None = None) -> str | None:
    """One line when pstack is missing or behind in a tool that is found. Never raises.

    Only the tools in `tools` count (default: every tool that is found).
    """
    try:
        found = [r for r in rows() if r.found and (tools is None or r.tool in tools)]
        if not found:
            return None  # no tool applies: no network
        latest = latest_version()
        missing, behind = [], []
        for row in found:
            state = row.state(latest)
            if state == "missing":
                missing.append(row.label)
            elif state == "behind":
                behind.append(f"{row.label} {row.installed} (latest {latest})")
        parts = []
        if missing:
            parts.append(f"missing for {', '.join(missing)}")
        if behind:
            parts.append(f"behind for {', '.join(behind)}")
        if not parts:
            return None
        return f"pstack skills: {'; '.join(parts)}. Run: {COMMAND}"
    except Exception:
        return None


def _state(memdir: Path) -> dict:
    return _read_json(memdir / STATE_NAME) or {}


def _save(memdir: Path, state: dict) -> None:
    with contextlib.suppress(OSError):
        if memdir.is_dir():
            (memdir / STATE_NAME).write_text(json.dumps(state) + "\n", encoding="utf-8")


def session_line(memdir: Path, agent: str | None = None, record: bool = False) -> str | None:
    """The advisory for the tool that runs this session, at most 3 sessions per version pair.

    The pair is the installed version and the latest version. A newer latest starts a new
    count. With `record`, this call is one session. Never raises.
    """
    try:
        if not load_config(memdir)["skills_check"]:
            return None
        tool = running_tool(agent)
        row = next((r for r in rows() if r.tool == tool), None)
        if row is None or not row.found:
            return None  # no tool applies: no network
        latest = latest_version()
        if row.state(latest) not in ("missing", "behind"):
            return None
        key = f"{row.installed or 'none'}->{latest or 'unknown'}"
        state = _state(memdir)
        entry = state.get("shown", {}).get(tool) or {}
        sessions = int(entry.get("sessions", 0)) if entry.get("key") == key else 0
        if sessions >= SHOWN_MAX:
            return None
        if record:
            state.setdefault("shown", {})[tool] = {"key": key, "sessions": sessions + 1}
            _save(memdir, state)
        return advisory([tool])
    except Exception:
        return None


def once_line(memdir: Path, record: bool = True) -> str | None:
    """For `init` and `migrate`: the advisory for every tool found, once per memory folder."""
    try:
        if not load_config(memdir)["skills_check"]:
            return None
        state = _state(memdir)
        line = None if state.get("mentioned") else advisory()
        if line and record:
            _save(memdir, {**state, "mentioned": True})
        return line
    except Exception:
        return None


# --- status ---------------------------------------------------------------------------


def run_status() -> int:
    latest = latest_version()
    print(f"pstack skills (latest: {latest or 'unknown'})")
    for row in rows():
        state = row.state(latest)
        if state == "not found":
            text = "not found"
        elif state == "missing":
            text = "not installed"
        elif state == "behind":
            text = f"installed {row.installed} (behind: latest is {latest})"
        elif latest is None:
            text = f"installed {row.installed} (latest unknown)"
        else:
            text = f"installed {row.installed} (up to date)"
        print(f"  {row.label}: {text}")
    return 0


# --- install --------------------------------------------------------------------------


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def copy_skills(tool: str, source: Path, version: str, commit: str) -> tuple[list[str], list[str]]:
    """Copy the pstack skills into the user skills folder. Return (copied, kept)."""
    base = skills_dir(tool)
    top = source / "pstack"
    names = sorted(p.name for p in (top / "skills").iterdir() if (p / "SKILL.md").is_file())
    if not names:
        raise OSError(f"no skills found in {top / 'skills'}")
    owned = {str(n) for n in _marker(tool).get("skills", [])}
    base.mkdir(parents=True, exist_ok=True)
    copied, kept = [], []
    for name in names:
        dest = base / name
        if os.path.lexists(dest) and name not in owned:
            kept.append(name)
            continue
        _remove(dest)
        shutil.copytree(top / "skills" / name, dest, symlinks=True)
        copied.append(name)
    for gone in sorted(owned - set(names)):
        _remove(base / gone)
    meta = base / MARKER_DIR
    meta.mkdir(exist_ok=True)
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt"):
        if (top / name).is_file() or (source / name).is_file():
            shutil.copyfile(
                top / name if (top / name).is_file() else source / name, meta / "LICENSE"
            )
            break
    record = {
        "name": "pstack",
        "version": version,
        "commit": commit,
        "source": REPO_URL,
        "skills": copied,
        "installed_at": stamp(now()),
    }
    (meta / MARKER).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return copied, kept


def _claude_steps(row: Row) -> list[list[str]]:
    if row.installed is None:
        steps = [] if _marketplace_known() else [["claude", "plugin", "marketplace", "add", REPO]]
        return [*steps, ["claude", "plugin", "install", PLUGIN, "--scope", "user"]]
    return [
        ["claude", "plugin", "marketplace", "update", MARKETPLACE],
        ["claude", "plugin", "update", PLUGIN, "--scope", "user"],
    ]


def _install_claude(row: Row, yes: bool) -> bool:
    steps = _claude_steps(row)
    verb = "install" if row.installed is None else "update"
    print(f"{row.label}: {verb} pstack (user scope)")
    for argv in steps:
        print(f"  {' '.join(argv)}")
    if not yes:
        return True
    if _which("claude") is None:
        print(
            f"error: {row.label}: the `claude` command is not on PATH, so pstack cannot be "
            f"{verb}ed. Put `claude` on PATH, then run: {COMMAND} --tool claude"
        )
        return False
    for argv in steps:
        code, out = _run(argv)
        if code:
            print(f"error: {row.label}: `{' '.join(argv)}` failed: {out[-400:] or code}")
            return False
    print(f"{row.label}: pstack {verb}d. Restart Claude Code to load it.")
    return True


def _install_copy(row: Row, latest: str | None, yes: bool, cloned: list) -> bool:
    verb = "install" if row.installed is None else "update"
    target = skills_dir(row.tool)
    shown = f" {latest}" if latest else ""
    print(f"{row.label}: {verb} pstack{shown}: copy the skills to {target}")
    if not yes:
        return True
    try:
        if not cloned:
            cloned.append(checkout())
        source, commit = cloned[0]
        version = (_read_json(source / "pstack" / "plugin.json") or {}).get("version")
        if not _key(version):
            raise OSError("pstack/plugin.json has no version")
        marker = _marker(row.tool)
        if marker.get("version") == version and marker.get("commit") == commit:
            print(f"{row.label}: pstack {version} is already there.")
            return True
        copied, kept = copy_skills(row.tool, source, version, commit)
    except Exception as exc:
        print(f"error: {row.label}: cannot fetch the pstack skills: {exc}")
        return False
    print(f"{row.label}: pstack {version} ({len(copied)} skill(s)) copied to {target}")
    if kept:
        print(f"  kept your own skill(s) with the same name: {', '.join(kept)}")
    return True


def run_install(tool: str | None, yes: bool) -> int:
    """Plan (default) or do (--yes) the install or update. The same command updates."""
    wanted = [t for t in TOOLS if detected(t)] if tool in (None, "all") else [tool]
    if not wanted:
        print("No agent tool found (looked for ~/.claude, ~/.codex and ~/.cursor).")
        print("Nothing to do. Use --tool NAME to pick one.")
        return 0
    latest = latest_version(force=yes)
    todo = []
    for row in rows():
        if row.tool in wanted and (row.installed is None or is_behind(row.installed, latest)):
            todo.append(row)
    if not todo:
        names = ", ".join(TOOLS[t] for t in wanted)
        print(f"Nothing to do. pstack is up to date for: {names}.")
        return 0
    cloned: list = []
    ok = True
    for row in todo:
        done = (
            _install_claude(row, yes)
            if row.tool == "claude"
            else _install_copy(row, latest, yes, cloned)
        )
        ok = ok and done
    if not yes:
        flag = f" --tool {tool}" if tool not in (None, "all") else ""
        print(f"This is the plan. Nothing changed. To do it: {COMMAND}{flag}")
    return 0 if ok else 1


def update_note() -> str:
    """For `skills_auto_update = true`: update what is missing or behind. Never raises.

    Return one line for the session, or an empty string when there was nothing to do.
    """
    try:
        latest = latest_version()
        stale = [r for r in rows() if r.state(latest) in ("missing", "behind")]
        if not stale:
            return ""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = run_install(None, True)
        names = ", ".join(r.label for r in stale)
        if code == 0:
            return f"pstack updated for {names} (user level). Restart the agent to load it.\n\n"
        error = next((x for x in out.getvalue().splitlines() if x.startswith("error:")), "")
        why = error.removeprefix("error: ")[:200] or "see `memory skills status`"
        return f"pstack auto-update failed ({why}).\n\n"
    except Exception:
        return ""
