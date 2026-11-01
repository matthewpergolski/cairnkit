"""Read config.toml from the memory folder."""

from __future__ import annotations

import difflib
import tomllib
from pathlib import Path

from cairnkit.githook import DEFAULT_GUARD_PATTERNS, DEFAULT_IDENTITY_PATTERNS

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


def _read(path: Path) -> tuple[dict, list[str], list[str], bool]:
    """Return (settings, errors, warnings, whether auto-tidy must stay off)."""
    config = {
        key: (value.copy() if isinstance(value, dict | list) else value)
        for key, value in DEFAULTS.items()
    }
    if not path.exists():
        return config, [], [], False
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return config, [f"cannot read it ({exc}); {OFF_NOTE}"], [], True
    errors: list[str] = []
    warnings: list[str] = []
    off = False
    mode = data.get("auto_tidy")
    if isinstance(mode, bool):
        config["auto_tidy"] = "on" if mode else "off"
    elif mode in AUTO_TIDY_MODES:
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
