"""Read config.toml from the memory folder."""

from __future__ import annotations

import difflib
import re
import tomllib
from pathlib import Path

from cairnkit.githook import DEFAULT_GUARD_PATTERNS, DEFAULT_IDENTITY_PATTERNS
from cairnkit.secretscan import KnownValues, mask, real_secrets

AUTO_TIDY_MODES = ("auto", "report", "on", "off")
DEFAULTS = {
    "areas": {},
    "auto_tidy": "auto",
    "skills_check": True,
    "skills_auto_update": False,
    "guard_patterns": DEFAULT_GUARD_PATTERNS,
    "guard_identity_patterns": DEFAULT_IDENTITY_PATTERNS,
}
KNOWN_KEYS = {"auto_tidy", "skills_check", "skills_auto_update", "areas", "commit_msg_guard"}
OLD_KEYS = {"short_term_days", "rules_file"}  # an older file may hold them; nothing reads them
OFF_NOTE = "auto-tidy is off until this is fixed"
_KEY_LINE = re.compile(r"\s*\[?\s*([\w-]+)")


def _defaults() -> dict:
    return {
        key: (value.copy() if isinstance(value, dict | list) else value)
        for key, value in DEFAULTS.items()
    }


def _read(path: Path) -> tuple[dict, list[str], list[str], bool]:
    """Return (settings, errors, warnings, whether auto-tidy must stay off)."""
    if not path.exists():
        return _defaults(), [], [], False
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return _defaults(), [f"cannot read it ({exc}); {OFF_NOTE}"], [], True
    return _read_data(data)


def _read_data(data: dict) -> tuple[dict, list[str], list[str], bool]:
    config = _defaults()
    errors: list[str] = []
    warnings: list[str] = []
    off = False
    mode = data.get("auto_tidy")
    if isinstance(mode, bool):
        config["auto_tidy"] = "on" if mode else "off"
    elif _mode_ok(mode):
        config["auto_tidy"] = mode
    elif "auto_tidy" in data:
        errors.append(
            f"auto_tidy = {mode!r} is not one of {', '.join(AUTO_TIDY_MODES)}; {OFF_NOTE}"
        )
        off = True
    for key in ("skills_check", "skills_auto_update"):
        if isinstance(data.get(key), bool):
            config[key] = data[key]
        elif key in data:
            errors.append(f"{key} = {data[key]!r} must be true or false")
    guard = data.get("commit_msg_guard")
    for key, name in (
        ("patterns", "guard_patterns"),
        ("identity_patterns", "guard_identity_patterns"),
    ):
        if isinstance(guard, dict) and isinstance(guard.get(key), list):
            patterns = [str(p) for p in guard[key] if str(p).strip()]
            if patterns:
                config[name] = patterns
    if "commit_msg_guard" in data and not isinstance(guard, dict):
        errors.append("commit_msg_guard must be a table")
    elif isinstance(guard, dict):
        for key in ("patterns", "identity_patterns"):
            if key in guard and not isinstance(guard[key], list):
                errors.append(f"commit_msg_guard.{key} must be a list")
    if isinstance(data.get("areas"), dict):
        config["areas"] = {str(k): str(v) for k, v in data["areas"].items()}
    elif "areas" in data:
        errors.append("areas must be a table")
    for key in sorted(set(data) - KNOWN_KEYS - OLD_KEYS):
        if "auto_tidy" not in data and difflib.get_close_matches(key, ["auto_tidy"], cutoff=0.7):
            errors.append(f"{key} is not a setting; did you mean auto_tidy? {OFF_NOTE}")
            off = True
        else:
            warnings.append(f"{key} is not a setting")
    return config, errors, warnings, off


def _mode_ok(mode: object) -> bool:
    return isinstance(mode, bool) or (isinstance(mode, str) and mode in AUTO_TIDY_MODES)


def _bad_keys(data: dict) -> set[str]:
    bad = set(data) - KNOWN_KEYS - OLD_KEYS
    if "auto_tidy" in data and not _mode_ok(data["auto_tidy"]):
        bad.add("auto_tidy")
    for key in ("skills_check", "skills_auto_update"):
        if key in data and not isinstance(data[key], bool):
            bad.add(key)
    if "areas" in data and not isinstance(data["areas"], dict):
        bad.add("areas")
    guard = data.get("commit_msg_guard")
    if "commit_msg_guard" in data and not (
        isinstance(guard, dict) and isinstance(guard.get("patterns"), list)
    ):
        bad.add("commit_msg_guard")
    return bad


def load_config(memdir: Path) -> dict:
    """Return settings. A bad file or a bad value gives the defaults, and no unattended retire."""
    config, _, _, off = _read(memdir / "config.toml")
    if off:
        config["auto_tidy"] = "off"
    return config


def config_problems(memdir: Path) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) about config.toml, for `memory check`."""
    _, errors, warnings, _ = _read(memdir / "config.toml")
    return [f"config.toml: {e}" for e in errors], [f"config.toml: {w}" for w in warnings]


def _parses(text: str) -> bool:
    try:
        tomllib.loads(text)
    except ValueError:
        return False
    return True


def _might_be_auto_tidy(line: str) -> bool:
    found = _KEY_LINE.match(line)
    key = found.group(1).lower() if found else ""
    return "auto" in line.lower() or bool(difflib.get_close_matches(key, ["auto_tidy"], cutoff=0.7))


def _bad_copies(memdir: Path) -> list[Path]:
    return sorted(memdir.glob("config.toml.bad*"))


def _next_bad_copy(memdir: Path) -> Path:
    path, number = memdir / "config.toml.bad", 2
    while path.exists():
        path, number = memdir / f"config.toml.bad.{number}", number + 1
    return path


def secrets_in_config(memdir: Path, known: KnownValues | None) -> list[str]:
    """One error for each line that holds a value. No line goes to the output."""
    problems = []
    for path in (memdir / "config.toml", *_bad_copies(memdir)):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, start=1):
            found = real_secrets(line, known)
            if found:
                problems.append(
                    f"{path.name}:{number}: holds a value that looks secret ({', '.join(found)})"
                )
    return problems


def _mask_bad_copies(memdir: Path, known: KnownValues | None) -> list[str]:
    done = []
    for path in _bad_copies(memdir):
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(real_secrets(line, known) for line in text.splitlines()):
            lines = text.splitlines(keepends=True)
            path.write_text("".join(mask(line, known) for line in lines), encoding="utf-8")
            done.append(f"{path.name}: masked the values that look secret.")
    return done


def repair_config(memdir: Path, known: KnownValues | None = None) -> list[str]:
    """Drop what is bad in config.toml, keep a copy, and return what it did.

    It keeps each line that still parses. When a dropped line could be the auto_tidy setting,
    the file says `off`, so that a repair never turns unattended retires back on. No value that
    looks secret stays in the file or in the copy.
    """
    path = memdir / "config.toml"
    done = _mask_bad_copies(memdir, known)
    errors, warnings = config_problems(memdir)
    raw = path.read_bytes() if path.exists() else b""
    text = raw.decode("utf-8", errors="ignore")
    if not errors and not warnings and not any(real_secrets(x, known) for x in text.splitlines()):
        return done
    copy = _next_bad_copy(memdir)
    has_secret = any(real_secrets(line, known) for line in text.splitlines())
    copy.write_bytes(mask(text, known).encode() if has_secret else raw)
    kept: list[str] = []
    dropped: list[str] = []
    for line in text.splitlines():
        if not real_secrets(line, known) and _parses("\n".join([*kept, line])):
            kept.append(line)
        else:
            dropped.append(line)
    # Dropping a table header can leave its keys at the top level, so this runs until it is clean.
    while bad := _bad_keys(tomllib.loads("\n".join(kept))):
        out = [line for line in kept if (m := _KEY_LINE.match(line)) and m.group(1) in bad]
        if not out:
            break
        kept = [line for line in kept if line not in out]
        dropped += out
    data = tomllib.loads("\n".join(kept))
    if any(_might_be_auto_tidy(line) for line in dropped) and not _mode_ok(data.get("auto_tidy")):
        kept.insert(0, 'auto_tidy = "off"')
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    # A key can hold the value too, so each name passes the mask.
    keys = [mask(m.group(1), known) for x in dropped if (m := _KEY_LINE.match(x))]
    shown = ", ".join(keys) or "bad bytes"
    return [*done, f"config.toml: dropped {shown}. The old file is {copy.name}."]
