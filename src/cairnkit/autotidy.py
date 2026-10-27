"""`memory tidy --auto`: retire the clear mechanical cases, with no person.

A retire is a status change, never a delete. Each one is a change record
(writer `auto-tidy`) and one line in `<memory>/auto-tidy.log`. The line holds
the command that undoes it. The session-start hook calls `retire`. So do the
personal pre-push and post-merge git hooks. A git event does not count as a
session start.

What it retires:

- `duplicate`: two active facts with the same words, kind and scope. The
  older one is superseded by the newest.
- `ended`: a short-term fact that is past its end date, or whose branch is
  merged (or gone).
- `file-gone`: a short-term fact whose `source` is `file:PATH`, when PATH
  is in no checkout of the project.

What it never touches: rules, pinned facts, and a fact that a person set back
to active. A near duplicate and a stale long fact need judgment, so they stay
with `memory tidy`.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from cairnkit.clock import now, parse_time, stamp
from cairnkit.memory import Memory
from cairnkit.paths import merged_checker
from cairnkit.schema import validate_record
from cairnkit.similar import exact_key
from cairnkit.state import effective_status
from cairnkit.store import append_records, locked

WRITER = "auto-tidy"
LOG_NAME = "auto-tidy.log"
LOCK_NAME = ".auto-tidy.lock"
STATE_NAME = ".auto-tidy-state.json"
WINDOW_SESSIONS = 3
WINDOW_DAYS = 7
SNIPPET = 70


@dataclass
class Retirement:
    id: str
    case: str
    status: str
    reason: str
    text: str = ""
    superseded_by: str | None = None

    @property
    def cid(self) -> str:
        """The same for the same retire, so two sessions write it once."""
        key = "|".join([self.id, self.status, self.reason, self.superseded_by or ""])
        return hashlib.sha1(key.encode()).hexdigest()[:12]

    def record(self, at: str) -> dict:
        rec = {
            "type": "change",
            "id": self.id,
            "at": at,
            "status": self.status,
            "reason": self.reason,
            "writer": WRITER,
            "cid": self.cid,
            "case": self.case,
        }
        if self.superseded_by:
            rec["superseded_by"] = self.superseded_by
        return rec

    def undo(self) -> str:
        step = f'memory change {self.id} --status active --reason "Kept on purpose."'
        if self.case == "ended":
            step += f" && memory keep {self.id}"
        return step


def _protected(state: dict) -> bool:
    """A rule, a pinned fact, or a fact that a person set back to active."""
    if state.get("kind") == "rule" or state.get("pinned"):
        return True
    return any(change.get("status") == "active" for change in state["history"])


def stated(state: dict) -> bool:
    """A person said it (basis `told`)."""
    return state.get("basis") == "told"


def outranks(old: dict, new: dict) -> bool:
    """True when `new` must not retire `old`: a person said `old`, and `new` is not their word."""
    return stated(old) and not stated(new)


def _file_gone(memory: Memory, state: dict) -> str | None:
    source = str(state.get("source", ""))
    if not source.startswith("file:"):
        return None
    rel = PurePosixPath(source[5:])
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        return None
    if any((checkout / rel).exists() for checkout in memory.project.checkouts):
        return None
    return source


def find(memory: Memory) -> list[Retirement]:
    moment = now()
    is_merged = merged_checker(memory.project.root)
    candidates = [
        s
        for s in sorted(memory.states.values(), key=lambda s: s["id"])
        if s.get("status") == "active" and not _protected(s)
    ]
    found: list[Retirement] = []
    taken: set[str] = set()
    for state in candidates:
        computed, why = effective_status(state, moment, is_merged)
        gone = _file_gone(memory, state) if state["scope"] == "short" else None
        text = " ".join(str(state.get("text", "")).split())[:SNIPPET]
        if computed == "expired":
            found.append(Retirement(state["id"], "ended", "expired", why or "Ended.", text))
        elif gone:
            reason = f"Source {gone} is in no checkout."
            found.append(Retirement(state["id"], "file-gone", "expired", reason, text))
        else:
            continue
        taken.add(state["id"])

    groups: dict[tuple, list[dict]] = {}
    for state in candidates:
        words = exact_key(str(state.get("text", "")))
        if state["id"] not in taken and words[0]:
            key = (state.get("kind"), state["scope"], state.get("until_branch_merged"), words)
            groups.setdefault(key, []).append(state)
    for same in groups.values():
        ordered = sorted(same, key=lambda s: (s.get("learned_at", ""), s["id"]))
        newest = ordered[-1]
        for old in ordered[:-1]:
            if outranks(old, newest):
                continue  # a person said it; the pair goes to the agent task
            text = " ".join(str(old.get("text", "")).split())[:SNIPPET]
            reason = f"Exact repeat of {newest['id']}."
            found.append(
                Retirement(old["id"], "duplicate", "superseded", reason, text, newest["id"])
            )
    return sorted(found, key=lambda r: r.id)


def write_log(memory: Memory, found: list[Retirement], at: str) -> None:
    """Add one line per retire. A line that is already there (same cid) is not added again.

    The log holds no fact text, so `memory purge` of a fact leaves nothing behind in it.
    """
    path = memory.dir / LOG_NAME
    with contextlib.suppress(OSError):
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        with path.open("a", encoding="utf-8") as log:
            for item in found:
                if f"cid {item.cid}" in old:
                    continue
                log.write(
                    f"{at} retired {item.id} [{item.case}] {item.reason} "
                    f"cid {item.cid} Undo: {item.undo()}\n"
                )


def retire(memory: Memory, dry_run: bool = False) -> list[Retirement]:
    """Retire the clear cases. Write the change records and the log. Return what was retired.

    A lock keeps two sessions apart. The second one reads the memory again inside
    the lock, so it finds nothing left to retire.
    """
    if dry_run:
        return find(memory)
    with locked(memory.dir / LOCK_NAME):
        memory.reload()
        found = find(memory)
        if not found:
            return found
        at = stamp(now())
        records = []
        for item in found:
            rec = item.record(at)
            problems = validate_record(rec)
            if problems:
                raise ValueError(f"{item.id}: {'; '.join(problems)}")
            records.append(rec)
        append_records(memory.writer_file(WRITER), records)
        write_log(memory, found, at)
    memory.reload()
    return found


def report(memory: Memory) -> list[Retirement]:
    """Say what `retire` would do. Log it once per distinct report. Change no fact."""
    found = find(memory)
    if not found:
        return found
    line = f"would retire {len(found)}: {', '.join(item.id for item in found)}"
    path = memory.dir / LOG_NAME
    with contextlib.suppress(OSError), locked(memory.dir / LOCK_NAME):
        old = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        last = next((ln.split(" ", 1)[1] for ln in reversed(old) if " would retire " in ln), "")
        if last != line:
            with path.open("a", encoding="utf-8") as log:
                log.write(f"{stamp(now())} {line}\n")
    return found


# --- "auto" mode: report first, then turn on by itself unless a retire was undone ---


def undone(memory: Memory) -> list[dict]:
    """Retires by auto-tidy that a person or an agent later set back to active."""
    out = []
    for state in memory.states.values():
        history = state.get("history", [])
        for i, change in enumerate(history):
            if change.get("writer") != WRITER or change.get("status") not in (
                "superseded",
                "expired",
            ):
                continue
            later = next((c for c in history[i + 1 :] if c.get("status") == "active"), None)
            if later:
                out.append(
                    {
                        "id": state["id"],
                        "text": " ".join(str(state.get("text", "")).split())[:SNIPPET],
                        "case": change.get("case", "unknown"),
                        "reason": change.get("reason", ""),
                        "undone_at": later.get("at", ""),
                    }
                )
    return sorted(out, key=lambda u: (u["undone_at"], u["id"]))


def _state(memory: Memory) -> dict:
    try:
        data = json.loads((memory.dir / STATE_NAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(memory: Memory, data: dict) -> None:
    with contextlib.suppress(OSError):
        (memory.dir / STATE_NAME).write_text(json.dumps(data, sort_keys=True), encoding="utf-8")


def open_undos(memory: Memory) -> list[dict]:
    """The undone retires that nobody has released yet (see `release`)."""
    released = _state(memory).get("released_at")
    return [
        u
        for u in undone(memory)
        if not released or parse_time(u["undone_at"]) > parse_time(released)
    ]


@dataclass
class Decision:
    mode: str  # "on" or "report"
    notes: list[str] = field(default_factory=list)  # always shown: it turned on, or it is held
    status: str = ""  # shown with a report: how long until it turns on


def decide(memory: Memory, *, count_session: bool = True) -> Decision:
    """Count this session start and say whether the hook retires or only reports.

    It turns on after WINDOW_SESSIONS session starts and WINDOW_DAYS days, and
    only while no retire is undone. An undo returns it to report only.

    A git push or merge passes `count_session=False`. That reads the same gate.
    It does not add a session, and it does not write the state file.
    """
    moment = now()
    with locked(memory.dir / LOCK_NAME):
        data = _state(memory)
        if count_session:
            data.setdefault("started_at", stamp(moment))
            data["sessions"] = int(data.get("sessions", 0)) + 1
        elif not data.get("started_at"):
            return Decision("report")
        days = (moment - parse_time(data["started_at"])).total_seconds() / 86400
        sessions = int(data.get("sessions", 0))
        notes = []
        status = ""
        if open_undos(memory):
            if count_session:
                data["on"] = False
            notes.append(
                "held report only: a retire was undone, so an agent task in "
                "proposals/tidy-followups.md says which rule to review"
            )
            mode = "report"
        elif data.get("on") or (sessions >= WINDOW_SESSIONS and days >= WINDOW_DAYS):
            mode = "on"
            if count_session and not data.get("on"):
                data["on"] = True
                notes.append(
                    f"turned itself on after {sessions} session starts and {int(days)} "
                    "days with no retire undone"
                )
        else:
            mode = "report"
            left_sessions = max(WINDOW_SESSIONS - sessions, 0)
            left_days = max(math.ceil(WINDOW_DAYS - days), 0)
            status = (
                f"report only; it turns itself on after {left_sessions} more session start(s) "
                f"and {left_days} more day(s) if no retire is undone"
            )
        if count_session:
            _save(memory, data)
    return Decision(mode, notes, status)


def release(memory: Memory) -> None:
    """After a review: forget the undos and start a new window."""
    moment = stamp(now())
    with locked(memory.dir / LOCK_NAME):
        _save(
            memory,
            {"started_at": moment, "sessions": 0, "on": False, "released_at": moment},
        )


def run_auto(memory: Memory, dry_run: bool) -> int:
    found = retire(memory, dry_run)
    if not found:
        print("Nothing to retire.")
        return 0
    verb = "Would retire" if dry_run else "Retired"
    print(f"{verb} {len(found)} fact(s):")
    for item in found:
        print(f"- {item.id} [{item.case}] {item.reason} {item.text!r}")
    if not dry_run:
        print(f"Log with the undo command for each: {memory.dir / LOG_NAME}")
    return 0
