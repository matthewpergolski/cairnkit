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
to active. A near duplicate is retired only when the word overlap is at least
the near threshold and the counts of numbers, negations and opposites match.
Otherwise it stays for `memory tidy`. A stale long fact is listed in
`proposals/stale-pending.md` and is not expired here.
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
from cairnkit.similar import analyze, exact_key, similarity
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
            taken.add(old["id"])
    found.extend(_near_duplicates(candidates, taken))
    return sorted(found, key=lambda r: r.id)


def _near_duplicates(candidates: list[dict], taken: set[str]) -> list[Retirement]:
    """Supersede the older fact when similarity passes and the meaning counts match."""
    pools: dict[tuple, list[dict]] = {}
    for state in candidates:
        if state["id"] in taken:
            continue
        pools.setdefault((state.get("kind"), state["scope"]), []).append(state)
    extra: list[Retirement] = []
    for group in pools.values():
        ordered = sorted(group, key=lambda s: (s.get("learned_at", ""), s["id"]))
        words = {s["id"]: analyze(str(s.get("text", ""))) for s in ordered}
        used: set[str] = set()
        for i, older in enumerate(ordered):
            if older["id"] in used:
                continue
            best: tuple[float, dict] | None = None
            for newer in ordered[i + 1 :]:
                if exact_key(str(older.get("text", ""))) == exact_key(str(newer.get("text", ""))):
                    continue
                if outranks(older, newer):
                    continue
                score = similarity(words[older["id"]], words[newer["id"]])
                if score is None:
                    continue
                if best is None or score > best[0]:
                    best = (score, newer)
            if best is None:
                continue
            score, newer = best
            text = " ".join(str(older.get("text", "")).split())[:SNIPPET]
            reason = f"similar_to {newer['id']} ({score:.0%} the same words)."
            extra.append(
                Retirement(older["id"], "near-duplicate", "superseded", reason, text, newer["id"])
            )
            used.add(older["id"])
    return extra


def note_stale(memory: Memory, days: int = 90) -> None:
    """Rewrite the stale-fact proposal. Do not expire the facts."""
    moment = now()
    linked = {link["id"] for s in memory.states.values() for link in s.get("links", [])}
    linked |= {s["id"] for s in memory.states.values() if s.get("links")}
    rows = []
    for state in sorted(memory.states.values(), key=lambda s: s["id"]):
        if state.get("status") != "active" or state.get("pinned"):
            continue
        if state.get("scope", "long") != "long" or state["id"] in linked:
            continue
        try:
            age = (moment - parse_time(state["learned_at"])).total_seconds() / 86400
        except (KeyError, ValueError, TypeError):
            continue
        if age > days:
            rows.append(state)
    path = memory.dir / "proposals" / "stale-pending.md"
    if not rows:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(exist_ok=True)
    lines = [
        "# Stale facts pending review",
        "",
        "Auto-tidy did not expire these. Run `memory tidy` and approve any expire.",
        "",
    ]
    for state in rows:
        text = " ".join(str(state.get("text", "")).split())[:SNIPPET]
        lines.append(f"- {state['id']}: {text}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


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
    note_stale(memory)
    if found:
        memory.reload()
    return found


def report(memory: Memory) -> list[Retirement]:
    """Say what `retire` would do. Log it once per distinct report. Change no fact."""
    found = find(memory)
    note_stale(memory)
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
    """True when pending candidates piled up, or the tidy state is older than a day."""
    data = _state(memory)
    every_days = memory.config.get("tidy_every_days", 1)
    batch = memory.config.get("tidy_candidate_batch", 3)
    try:
        every_days = float(every_days)
    except (TypeError, ValueError):
        every_days = 1
    try:
        batch = int(batch)
    except (TypeError, ValueError):
        batch = 3
    mark = data.get("last_tidy_at")
    if _pending_since(memory, mark if isinstance(mark, str) else None) >= batch:
        return True
    moment = _age_days(data, memory)
    return moment is not None and moment >= every_days


def _pending_since(memory: Memory, mark: str | None) -> int:
    from cairnkit.pending import pending as pending_rows

    count = 0
    for cand in pending_rows(memory):
        when = cand.created_at
        if not mark or (when and when > mark):
            count += 1
    return count


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
