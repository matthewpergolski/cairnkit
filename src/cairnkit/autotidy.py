"""`memory tidy --auto`: retire the clear mechanical cases, with no person.

A retire is a status change, never a delete. Each one is a change record
(writer `auto-tidy`) and one line in `<memory>/auto-tidy.log`. The line holds
the command that undoes it. The session-start hook calls `retire`. So do the
personal pre-push and post-merge git hooks. A git event does not count as a
session start.

What it retires:

- `duplicate`: two active facts with the same words in the same order, kind and scope.
  The older one is superseded by the newest.
- `ended`: a short-term fact that is past its end date, or whose branch is merged, or
  gone after a record said that it existed. With no such record, merged is unknown and
  the fact stays.
- `file-gone`: a short-term fact whose `source` is `file:PATH`, when PATH
  is in no checkout of the project.
- `near-duplicate`: an active fact with the same kind, scope and end branch as a newer one,
  when they differ only in case, plural, punctuation or a stop word. Any other differing word
  can make a different fact, so that pair goes to the agent task.

What it never touches: rules, pinned facts, and a fact that a person set back
to active. Age ends no fact: nothing here reads how old a long-term fact is.
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
from cairnkit.paths import UNKNOWN, branch_reader, branch_tip, merged_checker
from cairnkit.schema import validate_record
from cairnkit.selection import clean
from cairnkit.similar import exact_key, near_key
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
    # A mask hides what differs, so two masked facts can read the same and not be the same.
    if "[secret: " in f"{state.get('text')} {state.get('source')}":
        return True
    return any(change.get("status") == "active" for change in state["history"])


def stated(state: dict) -> bool:
    """A person said it (basis `told`)."""
    return state.get("basis") == "told"


def outranks(old: dict, new: dict) -> bool:
    """True when `new` must not retire `old`: a person said `old`, and `new` is not their word."""
    return stated(old) and not stated(new)


def _guess_over_seen(old: dict, new: dict) -> bool:
    """A guess with other words must not end an observation. `guess` is also the default basis."""
    return old.get("basis") == "seen" and new.get("basis") == "guess"


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
        if state["id"] not in taken and words:
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
            taken.add(old["id"])
    found.extend(_near_duplicates(candidates, taken))
    return sorted(found, key=lambda r: r.id)


def _near_duplicates(candidates: list[dict], taken: set[str]) -> list[Retirement]:
    """Supersede an older fact with the newest one that differs only in form."""
    groups: dict[tuple, list[dict]] = {}
    for state in candidates:
        key = near_key(str(state.get("text", "")))
        if state["id"] not in taken and key:
            group = (state.get("kind"), state["scope"], state.get("until_branch_merged"), key)
            groups.setdefault(group, []).append(state)
    extra: list[Retirement] = []
    for same in groups.values():
        ordered = sorted(same, key=lambda s: (s.get("learned_at", ""), s["id"]))
        for i, old in enumerate(ordered[:-1]):
            newer = next(
                (
                    new
                    for new in reversed(ordered[i + 1 :])
                    if not outranks(old, new) and not _guess_over_seen(old, new)
                ),
                None,
            )
            if newer:
                text = " ".join(str(old.get("text", "")).split())[:SNIPPET]
                reason = (
                    f"similar_to {newer['id']}: only case, plural, punctuation or a stop word "
                    "differ."
                )
                extra.append(
                    Retirement(old["id"], "near-duplicate", "superseded", reason, text, newer["id"])
                )
    return extra


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


def _end_branch(state: dict) -> str | None:
    """The end branch of a short-term fact that is still active."""
    if state.get("status") != "active" or state.get("scope") != "short":
        return None
    return state.get("until_branch_merged")


def record_branch_tips(memory: Memory) -> None:
    """Record the tip of each end branch with no record, so that its later absence means it ended.

    This covers a branch that came after the note, and a fact from before the record existed.
    It changes no status. The first tip is enough. A cid keeps two sessions to one record.
    """
    at = stamp(now())
    records = []
    for state in sorted(memory.states.values(), key=lambda s: s["id"]):
        branch = _end_branch(state)
        tip = branch and "branch_tip" not in state and branch_tip(memory.project.root, branch)
        if tip:
            records.append(
                {
                    "type": "change",
                    "id": state["id"],
                    "at": at,
                    "branch_tip": tip,
                    "writer": WRITER,
                    "cid": hashlib.sha1(f"{state['id']}|{tip}".encode()).hexdigest()[:12],
                }
            )
    if records:
        append_records(memory.writer_file(WRITER), records)
        memory.reload()


def unknown_branches(memory: Memory) -> list[tuple[str, str]]:
    """(fact id, branch) for each active note whose branch git cannot read here."""
    read = branch_reader(memory.project.root)
    found = []
    for state in sorted(memory.states.values(), key=lambda s: s["id"]):
        branch = _end_branch(state)
        if branch and read(branch, state.get("branch_tip")) == UNKNOWN:
            found.append((state["id"], branch))
    return found


def print_unknown(memory: Memory) -> None:
    found = unknown_branches(memory)
    if not found:
        return
    print(
        f"Kept {len(found)} short-term fact(s). Merged is unknown: the branch is in no ref here, "
        "and no record says that this clone held it."
    )
    for fact_id, branch in found:
        print(clean(f"- {fact_id} until {branch}"))
    print('To end one that is over: memory change ID --status expired --reason "..."')


def retire(memory: Memory, dry_run: bool = False) -> list[Retirement]:
    """Retire the clear cases. Write the change records and the log. Return what was retired.

    A lock keeps two sessions apart. The second one reads the memory again inside
    the lock, so it finds nothing left to retire.
    """
    if dry_run:
        return find(memory)
    record_branch_tips(memory)
    with locked(memory.dir / LOCK_NAME):
        memory.reload()
        found = find(memory)
        if found:
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
    if found:
        memory.reload()
    return found


def report(memory: Memory) -> list[Retirement]:
    """Say what `retire` would do. Log it once per distinct report. Change no status."""
    record_branch_tips(memory)
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


def periodic_due(memory: Memory) -> bool:
    """True when the tidy state is older than a day, so a long session still tidies."""
    data = _state(memory)
    age = _age_days(data, memory)
    return age is not None and age >= 1


def _age_days(data: dict, memory: Memory) -> float | None:
    mark = data.get("last_tidy_at") or data.get("started_at")
    if isinstance(mark, str) and mark:
        try:
            return (now() - parse_time(mark)).total_seconds() / 86400
        except (ValueError, TypeError):
            return None
    path = memory.dir / STATE_NAME
    if not path.exists():
        return None
    return (now().timestamp() - path.stat().st_mtime) / 86400


def mark_tidied(memory: Memory) -> None:
    with locked(memory.dir / LOCK_NAME):
        data = _state(memory)
        data["last_tidy_at"] = stamp(now())
        _save(memory, data)


def run_auto(memory: Memory, dry_run: bool) -> int:
    found = retire(memory, dry_run)
    print_unknown(memory)
    if not found:
        print("Nothing to retire.")
        return 0
    verb = "Would retire" if dry_run else "Retired"
    print(f"{verb} {len(found)} fact(s):")
    for item in found:
        print(clean(f"- {item.id} [{item.case}] {item.reason} {item.text!r}"))
    if not dry_run:
        print(f"Log with the undo command for each: {memory.dir / LOG_NAME}")
    return 0
