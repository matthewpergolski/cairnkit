"""Read config.toml from the memory folder."""

from __future__ import annotations

import tomllib
from pathlib import Path

from cairnkit.githook import DEFAULT_GUARD_PATTERNS

AUTO_TIDY_MODES = ("auto", "report", "on", "off")
DEFAULTS = {
    "short_term_days": 14,
    "areas": {},
    "rules_file": "AGENTS.md",
    "auto_tidy": "auto",
    "skills_check": True,
    "skills_auto_update": False,
    "guard_patterns": DEFAULT_GUARD_PATTERNS,
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
    if isinstance(data.get("short_term_days"), int) and data["short_term_days"] > 0:
        config["short_term_days"] = data["short_term_days"]
    if isinstance(data.get("rules_file"), str) and data["rules_file"].strip():
        config["rules_file"] = data["rules_file"].strip()
    mode = data.get("auto_tidy")
    if isinstance(mode, bool):
        config["auto_tidy"] = "on" if mode else "off"
    elif mode in AUTO_TIDY_MODES:
        config["auto_tidy"] = mode
    for key in ("skills_check", "skills_auto_update"):
        if isinstance(data.get(key), bool):
            config[key] = data[key]
    guard = data.get("commit_msg_guard")
    if isinstance(guard, dict) and isinstance(guard.get("patterns"), list):
        patterns = [str(p) for p in guard["patterns"] if str(p).strip()]
        if patterns:
            config["guard_patterns"] = patterns
    if isinstance(data.get("areas"), dict):
        config["areas"] = {str(k): str(v) for k, v in data["areas"].items()}
    return config
