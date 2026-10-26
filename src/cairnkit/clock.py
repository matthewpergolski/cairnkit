"""Times: now, and parsing of dates and date-times."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime


def now() -> datetime:
    """The current time with its offset. MEMORY_NOW (ISO 8601) overrides it for tests."""
    fixed = os.environ.get("MEMORY_NOW")
    if fixed:
        return parse_time(fixed)
    return datetime.now().astimezone().replace(microsecond=0)


def stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    """Parse a date or a date-time. A date is midnight UTC. A naive time is UTC."""
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), datetime.min.time(), UTC)
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment


def is_time(value: object, need_offset: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    try:
        if len(value) == 10:
            date.fromisoformat(value)
            return not need_offset
        return datetime.fromisoformat(value).tzinfo is not None or not need_offset
    except ValueError:
        return False
