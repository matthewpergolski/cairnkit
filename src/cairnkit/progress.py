"""The step display of `memory update`.

A terminal stacks a cairn. Check, Fetch, Install, and Verify each add one
stone. Build runs and adds no stone. After success the summary line is the
flag. Piped output, a dumb terminal, CI, NO_COLOR, and an opt-out get one
plain line per step.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TextIO

STONE = "●"
TICK = 0.1
HIDE, SHOW, CLEAR = "\x1b[?25l", "\x1b[?25h", "\r\x1b[K"


@dataclass(frozen=True)
class StageSpec:
    """One update step. Build is a real step and adds no stone."""

    name: str
    weight: float
    stone: bool


STAGES: tuple[StageSpec, ...] = (
    StageSpec("Check", 1.0, True),
    StageSpec("Fetch", 1.0, True),
    StageSpec("Build", 4.0, False),
    StageSpec("Install", 4.0, True),
    StageSpec("Verify", 1.0, True),
)


def want_anim(stream: TextIO, env: Mapping[str, str] | None = None, opt_out: bool = False) -> bool:
    """True only when the cairn and the drip delay are allowed."""
    if opt_out:
        return False
    names = os.environ if env is None else env
    if names.get("CAIRNKIT_PLAIN") or names.get("MEMORY_PLAIN"):
        return False
    if names.get("NO_COLOR") is not None:
        return False
    if names.get("CI"):
        return False
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty) or not isatty():
        return False
    return names.get("TERM") != "dumb"


def _pyramid(count: int) -> list[str]:
    rows = [" ".join([STONE] * n) for n in range(1, count + 1)]
    if not rows:
        return []
    width = len(rows[-1])
    return [row.center(width) for row in rows]


class Progress:
    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        anim: bool | None = None,
        drip_delay: float = 0.04,
        stages: tuple[StageSpec, ...] = STAGES,
    ) -> None:
        self.out = stream or sys.stdout
        self.live = want_anim(self.out) if anim is None else bool(anim)
        self.drip_delay = drip_delay
        self.stages = stages
        self.stacked = 0
        self.label: str | None = None
        self.step_started = 0.0
        self.hidden = False
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.ticker: threading.Thread | None = None

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    def _stage(self, name: str) -> StageSpec | None:
        return next((stage for stage in self.stages if stage.name == name), None)

    def say(self, text: str) -> None:
        """One static line. On a terminal it goes above the cairn."""
        if not self.live:
            self._write(text + "\n")
            return
        with self.lock:
            self._write(CLEAR + text + "\n")
            if self.label:
                self._write(self._cairn_row())

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
            self._write(CLEAR + self._cairn_row())
        self.stop.clear()
        self.ticker = threading.Thread(target=self._tick, daemon=True)
        self.ticker.start()

    def done(self) -> None:
        if self.label is None:
            return
        self._stop_ticker()
        spec = self._stage(self.label)
        if spec is None or spec.stone:
            self.stacked += 1
        self.label = None
        if not self.live:
            self._write("done\n")
            return
        with self.lock:
            self._write(CLEAR + self._cairn_row())

    def fail(self) -> None:
        if self.label is None:
            return
        self._stop_ticker()
        label, self.label = self.label, None
        self.stacked = 0
        if not self.live:
            self._write("failed\n")
            return
        self._write(f"{CLEAR}  {label}... failed\n")

    def finish(self, summary: str) -> None:
        """The cairn and the summary on a terminal, or one plain summary line."""
        self.done()
        if not self.live:
            self._write(summary + "\n")
            return
        with self.lock:
            self._write(CLEAR)
            for line in _pyramid(self.stacked):
                self._write(line + "\n")
            self._write(summary + "\n")
        self.close()

    def drip(self, lines: list[str]) -> None:
        """Print each line. On a cairn, pause between lines."""
        for line in lines:
            self.say(line)
            if self.live and self.drip_delay > 0:
                time.sleep(self.drip_delay)

    def close(self) -> None:
        """Stop the display and show the cursor. Safe to call more than once."""
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
                self._write(CLEAR + self._cairn_row())

    def _cairn_row(self) -> str:
        stones = STONE * self.stacked
        elapsed = time.monotonic() - self.step_started if self.label else 0.0
        tail = f"  {self.label}  {elapsed:.1f}s" if self.label else ""
        row = f"  {stones}{tail}".rstrip()
        cols = shutil.get_terminal_size((80, 24)).columns
        return row[: max(cols - 1, 1)]
