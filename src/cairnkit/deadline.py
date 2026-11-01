"""A total time budget for one command, so that a slow git cannot outlast a hook timeout.

Without a total, each git call has its own timeout, and many calls add up past the agent's hook
timeout. The agent then starts with no memory. Each budget is under the shortest timeout of any
adapter for that event (see `adapters.py`). A test holds them to that.
"""

from __future__ import annotations

import contextlib
import math
import time
from collections.abc import Iterator

COMMAND_BUDGET = {
    "session-start": 7.0,  # timeout 10
    "subagent-start": 7.0,  # timeout 10
    "load": 7.0,
    "after-shell": 3.0,  # timeout 5
    "post-tool": 3.0,  # timeout 5
    "prompt": 3.0,  # timeout 5
    "pre-compact": 3.0,  # timeout 5
    "stop": 20.0,  # timeout 30
    # No hook runs these, but a tool that runs one should get an answer as fast as its shortest
    # hook. With the wait for the write lock (`store.WRITE_LOCK_FLOOR`), they stay under 5.
    "add": 3.0,
    "change": 3.0,
    "keep": 3.0,
    "purge": 3.0,
}

_end: float | None = None
_git_stuck = False
_git_cuts = 0


def left() -> float:
    """The seconds left in the budget. With no budget, there is no limit."""
    return math.inf if _end is None else _end - time.monotonic()


def has_time() -> bool:
    return left() > 0 and not git_stuck()


def git_stuck() -> bool:
    """True after a git call used its whole timeout. Inside a budget, git is not called again."""
    return _end is not None and _git_stuck


def git_cuts() -> int:
    """How many git calls of this process got no answer. Compare two reads, one before a step.

    A failed exit is an answer: git said no. A timeout, a call past the budget and a git that does
    not run are not. A caller must not read those as "no repo" or as "no branch".
    """
    return _git_cuts


def note_git_cut() -> None:
    global _git_cuts
    _git_cuts += 1


def note_git_timeout() -> None:
    global _git_stuck
    _git_stuck = _end is not None


@contextlib.contextmanager
def within(seconds: float | None) -> Iterator[None]:
    """Run the block with at most this many seconds left. None adds no limit."""
    global _end, _git_stuck
    before = _end
    if seconds is not None:
        end = time.monotonic() + seconds
        _end = end if before is None else min(before, end)
    try:
        yield
    finally:
        _end = before
        if before is None:
            _git_stuck = False
