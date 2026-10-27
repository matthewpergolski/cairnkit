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
CATALOG = "pstack-catalog.json"


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


def record_catalog(count: int, names: list[str] | None = None) -> None:
    """Remember how many pstack skills the source has (for status counts). Never raises."""
    if count < 0:
        return
    record: dict = {"count": count, "checked": stamp(now())}
    if names is not None:
        record["skills"] = list(names)
    with contextlib.suppress(OSError):
        path = cache_dir() / CATALOG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def catalog_count() -> int | None:
    """How many skills the last-seen pstack source had, or None."""
    data = _read_json(cache_dir() / CATALOG) or {}
    count = data.get("count")
    return count if isinstance(count, int) and count >= 0 else None


def source_skill_names(source: Path) -> list[str]:
    """Skill folder names under pstack/skills that have a SKILL.md."""
    folder = source / "pstack" / "skills"
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if (p / "SKILL.md").is_file())


def _claude_install_path() -> Path | None:
    data = _read_json(Path.home() / ".claude" / "plugins" / "installed_plugins.json") or {}
    entries = (data.get("plugins") or {}).get(PLUGIN) or []
    entries = sorted(
        (e for e in entries if isinstance(e, dict)), key=lambda e: e.get("scope") != "user"
    )
    for entry in entries:
        where = Path(str(entry.get("installPath", "")))
        if where.is_dir():
            return where
    return None


def installed_skill_count(tool: str) -> int | None:
    """How many pstack skills this tool currently has, or None when unknown."""
    if tool == "claude":
        where = _claude_install_path()
        if where is None:
            return None
        folder = where / "skills"
        # Claude loads the plugin as a unit; no skills/ means we cannot count yet.
        if not folder.is_dir():
            return None
        return sum(1 for p in folder.iterdir() if (p / "SKILL.md").is_file())
    owned = _marker(tool).get("skills")
    if not isinstance(owned, list):
        return None
    base = skills_dir(tool)
    return sum(1 for n in owned if isinstance(n, str) and (base / n / "SKILL.md").is_file())


def installed_version(tool: str) -> str | None:
    """The installed pstack version for a tool, or None."""
    if tool != "claude":
        version = _marker(tool).get("version")
        return version if isinstance(version, str) else None
    where = _claude_install_path()
    if where is not None:
        for name in (where / "plugin.json", where / ".claude-plugin" / "plugin.json"):
            version = (_read_json(name) or {}).get("version")
            if isinstance(version, str):
                return version
    data = _read_json(Path.home() / ".claude" / "plugins" / "installed_plugins.json") or {}
    entries = (data.get("plugins") or {}).get(PLUGIN) or []
    entries = sorted(
        (e for e in entries if isinstance(e, dict)), key=lambda e: e.get("scope") != "user"
    )
    for entry in entries:
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
    skills: int | None = None

    @property
    def label(self) -> str:
        return TOOLS[self.tool]

    def state(self, latest: str | None, available: int | None = None) -> str:
        """not found, missing, behind, partial or current."""
        if not self.found:
            return "not found"
        if self.installed is None:
            return "missing"
        if is_behind(self.installed, latest):
            return "behind"
        if (
            available is not None
            and self.skills is not None
            and self.tool != "claude"
            and self.skills < available
        ):
            return "partial"
        return "current"


def rows() -> list[Row]:
    return [Row(t, detected(t), installed_version(t), installed_skill_count(t)) for t in TOOLS]


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


def _skills_phrase(row: Row, available: int | None) -> str:
    """`2/3 skills` when both sides are known, else a short owned count, else empty."""
    if row.skills is None:
        return ""
    if available is not None:
        return f"{row.skills}/{available} skills"
    return f"{row.skills} skill(s)"


def run_status() -> int:
    latest = latest_version()
    available = catalog_count()
    print(f"pstack skills (latest: {latest or 'unknown'})")
    for row in rows():
        state = row.state(latest, available)
        counts = _skills_phrase(row, available)
        extra = f" — {counts}" if counts else ""
        if state == "not found":
            text = "not found"
        elif state == "missing":
            text = "not installed"
        elif state == "behind":
            text = f"installed {row.installed}{extra} (behind: latest is {latest})"
        elif state == "partial":
            text = f"installed {row.installed}{extra} (partial)"
        elif latest is None:
            text = f"installed {row.installed}{extra} (latest unknown)"
        else:
            text = f"installed {row.installed}{extra} (up to date)"
        print(f"  {row.label}: {text}")
    return 0


# --- install --------------------------------------------------------------------------


def _remove(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def copy_skills(
    tool: str, source: Path, version: str, commit: str, adopt: bool = False
) -> tuple[list[str], list[str], list[str]]:
    """Copy the pstack skills into the user skills folder.

    Return (installed, adopted, skipped). With `adopt`, same-named folders that
    cairnkit does not own are replaced and listed in `adopted`. Without it they
    are left alone and listed in `skipped`. The marker records every skill we
    own after the copy (catalog minus skipped), not only the ones written this
    run.
    """
    base = skills_dir(tool)
    top = source / "pstack"
    names = source_skill_names(source)
    if not names:
        raise OSError(f"no skills found in {top / 'skills'}")
    record_catalog(len(names), names)
    owned = {str(n) for n in _marker(tool).get("skills", []) if isinstance(n, str)}
    base.mkdir(parents=True, exist_ok=True)
    installed, adopted, skipped = [], [], []
    for name in names:
        dest = base / name
        exists = os.path.lexists(dest)
        if exists and name not in owned and not adopt:
            skipped.append(name)
            continue
        if exists and name not in owned and adopt:
            adopted.append(name)
        _remove(dest)
        shutil.copytree(top / "skills" / name, dest, symlinks=True)
        installed.append(name)
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
    owned_now = [n for n in names if n not in skipped]
    record = {
        "name": "pstack",
        "version": version,
        "commit": commit,
        "source": REPO_URL,
        "skills": owned_now,
        "catalog": len(names),
        "installed_at": stamp(now()),
    }
    (meta / MARKER).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return installed, adopted, skipped


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


def _copy_needed(tool: str, source: Path, commit: str, adopt: bool) -> bool:
    """True when a copy install still has work: version drift, gaps, or adopt collisions."""
    marker = _marker(tool)
    version = (_read_json(source / "pstack" / "plugin.json") or {}).get("version")
    names = source_skill_names(source)
    owned = {str(n) for n in marker.get("skills", []) if isinstance(n, str)}
    base = skills_dir(tool)
    if marker.get("version") != version or marker.get("commit") != commit:
        return True
    for name in names:
        exists = os.path.lexists(base / name)
        if not exists:
            return True
        if name not in owned and adopt:
            return True
    return False


def _unowned_names(tool: str, names: list[str]) -> list[str]:
    owned = {str(n) for n in _marker(tool).get("skills", []) if isinstance(n, str)}
    base = skills_dir(tool)
    return [n for n in names if os.path.lexists(base / n) and n not in owned]


def _install_copy(row: Row, latest: str | None, yes: bool, cloned: list, adopt: bool) -> bool:
    verb = "install" if row.installed is None else "update"
    if adopt and row.installed is not None:
        verb = "adopt"
    target = skills_dir(row.tool)
    shown = f" {latest}" if latest else ""
    note = " (replace same-named folders)" if adopt else ""
    print(f"{row.label}: {verb} pstack{shown}: copy the skills to {target}{note}")
    if not yes:
        return True
    try:
        if not cloned:
            cloned.append(checkout())
        source, commit = cloned[0]
        version = (_read_json(source / "pstack" / "plugin.json") or {}).get("version")
        if not _key(version):
            raise OSError("pstack/plugin.json has no version")
        names = source_skill_names(source)
        if not _copy_needed(row.tool, source, commit, adopt):
            record_catalog(len(names), names)
            owned = installed_skill_count(row.tool) or 0
            skipped = _unowned_names(row.tool, names)
            print(
                f"{row.label}: pstack {version} is already there "
                f"({owned} skill(s) installed, {len(skipped)} skipped)."
            )
            if skipped:
                print(
                    f"  skipped {len(skipped)}: kept your own skill(s) with the same name: "
                    f"{', '.join(skipped)}"
                )
                print(f"  to replace them: {COMMAND} --tool {row.tool} --adopt --yes")
            return True
        installed, adopted, skipped = copy_skills(row.tool, source, version, commit, adopt=adopt)
    except Exception as exc:
        print(f"error: {row.label}: cannot fetch the pstack skills: {exc}")
        return False
    print(
        f"{row.label}: pstack {version} ({len(installed)} skill(s) installed, "
        f"{len(skipped)} skipped) copied to {target}"
    )
    if adopted:
        print(f"  adopted (replaced) {len(adopted)} same-named folder(s): {', '.join(adopted)}")
    if skipped:
        print(
            f"  skipped {len(skipped)}: kept your own skill(s) with the same name: "
            f"{', '.join(skipped)}"
        )
        print(f"  to replace them: {COMMAND} --tool {row.tool} --adopt --yes")
    return True


def _row_needs_install(row: Row, latest: str | None, available: int | None, adopt: bool) -> bool:
    if not row.found:
        return False
    state = row.state(latest, available)
    if state in ("missing", "behind", "partial"):
        return True
    return bool(
        adopt
        and row.tool != "claude"
        and row.installed is not None
        and (available is None or row.skills is None or row.skills < available)
    )


def run_install(tool: str | None, yes: bool, adopt: bool = False) -> int:
    """Plan (default) or do (--yes) the install or update. The same command updates.

    With `adopt` (also `--all`), same-named skill folders are replaced so every
    pstack skill is installed. Without it, a skill of yours with the same name
    is kept and counted as skipped.
    """
    wanted = [t for t in TOOLS if detected(t)] if tool in (None, "all") else [tool]
    if not wanted:
        print("No agent tool found (looked for ~/.claude, ~/.codex and ~/.cursor).")
        print("Nothing to do. Use --tool NAME to pick one.")
        return 0
    latest = latest_version(force=yes)
    available = catalog_count()
    todo = [
        row
        for row in rows()
        if row.tool in wanted and _row_needs_install(row, latest, available, adopt)
    ]
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
            else _install_copy(row, latest, yes, cloned, adopt)
        )
        ok = ok and done
    if not yes:
        flag = f" --tool {tool}" if tool not in (None, "all") else ""
        adopt_flag = " --adopt" if adopt else ""
        print(f"This is the plan. Nothing changed. To do it: {COMMAND}{flag}{adopt_flag}")
    return 0 if ok else 1


def update_note() -> str:
    """For `skills_auto_update = true`: update what is missing or behind. Never raises.

    Return one line for the session, or an empty string when there was nothing to do.
    """
    try:
        latest = latest_version()
        available = catalog_count()
        stale = [
            r for r in rows() if r.state(latest, available) in ("missing", "behind", "partial")
        ]
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
