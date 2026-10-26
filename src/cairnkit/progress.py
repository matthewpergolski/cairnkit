"""The step display of `memory update`.

A terminal shows one bar for the whole update, with the current step and the
time. Piped output and TERM=dumb get one plain line per step. NO_COLOR keeps
the bar and drops color.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import threading
import time
from typing import TextIO

WEIGHTS = {"Check": 1.0, "Fetch": 1.0, "Build": 4.0, "Install": 4.0, "Verify": 1.0}
BAR_WIDTH = 32
MIN_BAR_WIDTH = 8
TICK = 0.1
HIDE, SHOW, CLEAR = "\x1b[?25l", "\x1b[?25h", "\r\x1b[K"


class Progress:
    def __init__(self, stream: TextIO | None = None, steps: tuple[str, ...] = tuple(WEIGHTS)):
        self.out = stream or sys.stdout
        isatty = getattr(self.out, "isatty", None)
        self.live = bool(isatty and isatty()) and os.environ.get("TERM") != "dumb"
        self.color = self.live and not os.environ.get("NO_COLOR")
        self.total = sum(WEIGHTS.get(step, 1.0) for step in steps) or 1.0
        self.done_weight = 0.0
        self.label: str | None = None
        self.step_started = 0.0
        self.hidden = False
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.ticker: threading.Thread | None = None

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def say(self, text: str) -> None:
        """One static line. On a terminal it goes above the bar."""
        if not self.live:
            self._write(text + "\n")
            return
        with self.lock:
            self._write(CLEAR + text + "\n")
            if self.label:
                self._write(self._row())

    def start(self, label: str) -> None:
        self.label = label
        self.step_started = time.monotonic()
        if not self.live:
            self._write(f"  {label}... ")
            return
        with self.lock:
            if not self.hidden:
                self.hidden = True
                self._write(HIDE)
            self._write(CLEAR + self._row())
        self.stop.clear()
        self.ticker = threading.Thread(target=self._tick, daemon=True)
        self.ticker.start()

    def done(self) -> None:
        if self.label is None:
            return
        self._stop_ticker()
        self.done_weight += WEIGHTS.get(self.label, 1.0)
        self.label = None
        if not self.live:
            self._write("done\n")

    def fail(self) -> None:
        if self.label is None:
            return
        self._stop_ticker()
        label, self.label = self.label, None
        if not self.live:
            self._write("failed\n")
            return
        mark = "\x1b[31m✖\x1b[0m" if self.color else "✖"
        self._write(f"{CLEAR}  {mark} {label}\n")

    def finish(self, summary: str) -> None:
        """A full bar, then the one-line result under it."""
        self.done()
        if not self.live:
            self._write(summary + "\n")
            return
        self.done_weight = self.total
        self._write(f"{CLEAR}{self._row()}\n  ◇ {summary}\n")
        self.close()

    def close(self) -> None:
        """Stop the bar and show the cursor. Safe to call more than once."""
        self._stop_ticker()
        if self.live and self.label is not None:
            self._write(CLEAR)
            self.label = None
        if self.hidden:
            self.hidden = False
            self._write(SHOW)

    def _stop_ticker(self) -> None:
        self.stop.set()
        if self.ticker is not None:
            self.ticker.join()
            self.ticker = None

    def _tick(self) -> None:
        while not self.stop.wait(TICK):
            with self.lock:
                self._write(CLEAR + self._row())

    def _row(self) -> str:
        elapsed = time.monotonic() - self.step_started if self.label else 0.0
        current = 0.0
        if self.label:
            # Fill toward the step's share without reaching it, so the bar moves.
            weight = WEIGHTS.get(self.label, 1.0)
            current = weight * 0.9 * (1 - math.exp(-elapsed / (2 * weight)))
        fraction = min((self.done_weight + current) / self.total, 1.0)
        label = self.label or ""
        tail = f" {label}  {elapsed:.1f}s" if self.label else ""
        cols = shutil.get_terminal_size((80, 24)).columns
        width = min(BAR_WIDTH, cols - 4 - len(tail))
        if width < MIN_BAR_WIDTH:
            return f"  {tail.strip()}"[: max(cols - 1, 1)]
        filled = round(fraction * width)
        if self.color:
            bar = f"\x1b[38;5;43m{'━' * filled}\x1b[38;5;240m{'━' * (width - filled)}\x1b[0m"
        else:
            bar = "━" * filled + "─" * (width - filled)
        return f"  {bar}{tail}"
