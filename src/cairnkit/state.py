"""Fold facts and changes into the current state of each fact."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from cairnkit.clock import now as clock_now
from cairnkit.clock import parse_time


def _when(value: object) -> datetime:
    try:
        return parse_time(str(value))
    except ValueError:
        return datetime.min.replace(tzinfo=clock_now().tzinfo)


def fold(records: list[dict]) -> dict[str, dict]:
    """Return {id: state}. A state is the fact with its changes applied in order of `at`.

    The state has `history` (the change records, in order) and, for a purged
    fact, `status` "purged" and no content.
    """
    facts: dict[str, dict] = {}
    changes: list[tuple[datetime, int, dict]] = []
    for index, rec in enumerate(records):
        kind = rec.get("type")
        if kind == "fact" and rec.get("id") not in facts:
            state = dict(rec)
            state["links"] = list(rec.get("links", []))
            state["scope"] = rec.get("scope", "long")
            state["history"] = []
            facts[rec["id"]] = state
        elif kind == "change":
            changes.append((_when(rec.get("at")), index, rec))
        elif kind == "tombstone":
            facts[rec["id"]] = {
                "id": rec["id"],
                "status": "purged",
                "purged_at": rec.get("at"),
                "reason": rec.get("reason"),
                "links": [],
                "history": [],
            }
    seen_cids: set[str] = set()
    for _, _, change in sorted(changes, key=lambda item: (item[0], item[1])):
        cid = change.get("cid")
        if cid:  # two sessions that wrote the same change write it once
            if cid in seen_cids:
                continue
            seen_cids.add(cid)
        state = facts.get(change.get("id"))
        if state is None or state["status"] == "purged":
            continue
        for name in ("status", "scope", "superseded_by", "held_by", "enforced_by"):
            if name in change:
                state[name] = change[name]
        if "enforced_by" in change and change["enforced_by"] is None:
            del state["enforced_by"]
        if "reason" in change and "status" in change:
            state["reason"] = change["reason"]
        state["links"].extend(change.get("add_links", []))
        state["history"].append(change)
    return facts


def effective_status(
    state: dict,
    now: str | datetime | None = None,
    is_merged: Callable[[str], bool] | None = None,
) -> tuple[str, str | None]:
    """Return (status, reason). A short-term fact past its end reads as expired.

    This is computed at read time. Nothing is written.
    """
    status = state.get("status", "active")
    if status != "active" or state.get("scope", "long") != "short":
        return status, state.get("reason")
    moment = parse_time(now) if isinstance(now, str) else (now or clock_now())
    expires = state.get("expires_at")
    if expires:
        try:
            if parse_time(expires) <= moment:
                return "expired", f"short-term fact ended on {expires}"
        except ValueError:
            pass
    branch = state.get("until_branch_merged")
    if branch and is_merged is not None and is_merged(branch):
        return "expired", f"short-term fact ended when branch {branch} was merged"
    return "active", None
