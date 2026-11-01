"""Read config.toml from the memory folder."""

from __future__ import annotations

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


def load_config(memdir: Path) -> dict:
    """Return settings. A missing or bad file gives the defaults."""
    config = {
        key: (value.copy() if isinstance(value, dict | list) else value)
        for key, value in DEFAULTS.items()
    }
    path = memdir / "config.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return config
    mode = data.get("auto_tidy")
    if isinstance(mode, bool):
        config["auto_tidy"] = "on" if mode else "off"
    elif mode in AUTO_TIDY_MODES:
        config["auto_tidy"] = mode
    for key in ("skills_check", "skills_auto_update"):
        if isinstance(data.get(key), bool):
            config[key] = data[key]
    guard = data.get("commit_msg_guard")
    for key, name in (
        ("patterns", "guard_patterns"),
        ("identity_patterns", "guard_identity_patterns"),
    ):
        if isinstance(guard, dict) and isinstance(guard.get(key), list):
            patterns = [str(p) for p in guard[key] if str(p).strip()]
            if patterns:
                config[name] = patterns
    if isinstance(data.get("areas"), dict):
        config["areas"] = {str(k): str(v) for k, v in data["areas"].items()}
    return config
