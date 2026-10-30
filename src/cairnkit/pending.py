"""Pending auto-proposed candidates. Not facts until accepted.

Stored under `proposals/auto-candidates.jsonl` as append-only lines. A
candidate starts pending. Accept writes a real fact through the normal add
path; dismiss only records a decision. Pending rows never enter load or
selection.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

from cairnkit.clock import now, stamp
from cairnkit.memory import Memory
from cairnkit.store import locked

FILE = "proposals/auto-candidates.jsonl"
LOCK = ".auto-candidates.lock"
STATUSES = ("pending", "accepted", "dismissed")


@dataclass
class Candidate:
    id: str
    text: str
    kind: str
    source: str
    status: str = "pending"
    origin: str = "draft"
    area: str | None = None
    basis: str = "guess"
    summary: str | None = None
    created_at: str = ""
    commit: str | None = None
    paths: list[str] = field(default_factory=list)
    fact_id: str | None = None
    reason: str | None = None

    def record(self) -> dict:
        data = {"type": "candidate", **asdict(self)}
        if data.get("created_at"):
            data["at"] = data["created_at"]
        return {k: v for k, v in data.items() if v is not None and v != [] and v != ""}


def _path(memory: Memory) -> Path:
    return memory.dir / FILE


def _new_id(day: str, text: str, source: str) -> str:
    digest = hashlib.sha1(f"{text}|{source}".encode()).hexdigest()[:4]
    return f"c-{day}-{digest}"


def stable_id(text: str, source: str, when=None) -> str:
    moment = when or now()
    base = _new_id(moment.strftime("%Y%m%d"), text, source)
    return base


def unique_id(memory: Memory, text: str, source: str) -> str:
    """A stable id for the same text+source; a free suffix when that id is taken."""
    moment = now()
    day = moment.strftime("%Y%m%d")
    base = _new_id(day, text, source)
    states = fold(memory)
    if base not in states or (states[base].status == "pending" and states[base].text == text):
        return base
    for _ in range(32):
        candidate = f"c-{day}-{secrets.token_hex(2)}"
        if candidate not in states:
            return candidate
    return f"c-{day}-{secrets.token_hex(2)}"


def fold(memory: Memory) -> dict[str, Candidate]:
    """Latest state per id. Decision lines override the candidate."""
    path = _path(memory)
    out: dict[str, Candidate] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(rec, dict) or "id" not in rec:
            continue
        kind = rec.get("type", "candidate")
        if kind == "candidate":
            out[rec["id"]] = Candidate(
                id=rec["id"],
                text=str(rec.get("text", "")),
                kind=str(rec.get("kind", "fact")),
                source=str(rec.get("source", "")),
                status=str(rec.get("status", "pending")),
                origin=str(rec.get("origin", "draft")),
                area=rec.get("area") or None,
                basis=str(rec.get("basis") or "guess"),
                summary=rec.get("summary") or None,
                created_at=str(rec.get("created_at") or rec.get("at") or ""),
                commit=rec.get("commit"),
                paths=list(rec.get("paths") or []),
                fact_id=rec.get("fact_id"),
                reason=rec.get("reason"),
            )
        elif kind == "decision" and rec["id"] in out:
            cand = out[rec["id"]]
            cand.status = str(rec.get("status", cand.status))
            if rec.get("fact_id"):
                cand.fact_id = rec["fact_id"]
            if rec.get("reason"):
                cand.reason = rec["reason"]
    return out


def pending(memory: Memory) -> list[Candidate]:
    return sorted(
        (c for c in fold(memory).values() if c.status == "pending"),
        key=lambda c: (c.created_at, c.id),
    )


def append(memory: Memory, records: list[dict]) -> None:
    if not records:
        return
    path = _path(memory)
    with locked(memory.dir / LOCK):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")


def add_candidates(memory: Memory, items: list[Candidate]) -> list[Candidate]:
    """Append new pending candidates. Skip exact text already pending or accepted."""
    with locked(memory.dir / LOCK):
        memory.reload()
        existing = fold(memory)
        seen_text = {
            " ".join(c.text.lower().split())
            for c in existing.values()
            if c.status in ("pending", "accepted")
        }
        fresh: list[Candidate] = []
        for item in items:
            key = " ".join(item.text.lower().split())
            if not key or key in seen_text:
                continue
            if item.id in existing and existing[item.id].status == "pending":
                continue
            if not item.created_at:
                item.created_at = stamp(now())
            item.status = "pending"
            fresh.append(item)
            seen_text.add(key)
        if fresh:
            path = _path(memory)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                for item in fresh:
                    fh.write(
                        json.dumps(item.record(), ensure_ascii=False, separators=(",", ":")) + "\n"
                    )
        return fresh


def decide(
    memory: Memory,
    cand_id: str,
    status: str,
    *,
    fact_id: str | None = None,
    reason: str | None = None,
) -> Candidate:
    if status not in ("accepted", "dismissed"):
        raise ValueError(f"status must be accepted or dismissed, not {status!r}")
    states = fold(memory)
    if cand_id not in states:
        raise KeyError(cand_id)
    cand = states[cand_id]
    if cand.status == status:
        if fact_id and not cand.fact_id:
            append(
                memory,
                [
                    {
                        "type": "decision",
                        "id": cand_id,
                        "status": status,
                        "at": stamp(now()),
                        "fact_id": fact_id,
                    }
                ],
            )
            cand.fact_id = fact_id
        return cand
    if cand.status != "pending":
        raise ValueError(f"{cand_id} is already {cand.status}")
    rec = {
        "type": "decision",
        "id": cand_id,
        "status": status,
        "at": stamp(now()),
    }
    if fact_id:
        rec["fact_id"] = fact_id
    if reason:
        rec["reason"] = reason
    append(memory, [rec])
    cand.status = status
    cand.fact_id = fact_id
    cand.reason = reason
    return cand


def _text_key(text: str) -> str:
    return " ".join(text.lower().split())


def mark_matching(memory: Memory, text: str, fact_id: str | None) -> None:
    """Accept every pending candidate whose text is this fact. Safe to repeat."""
    key = _text_key(text)
    if not key:
        return
    for cand in list(fold(memory).values()):
        if cand.status != "pending" or _text_key(cand.text) != key:
            continue
        decide(memory, cand.id, "accepted", fact_id=fact_id)


def count_pending(memory: Memory) -> int:
    return len(pending(memory))
