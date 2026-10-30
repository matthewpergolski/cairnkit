"""`memory candidates list|accept|reject`: review auto-proposed pending facts."""

from __future__ import annotations

import argparse
import sys
from types import SimpleNamespace

from cairnkit.memory import Memory
from cairnkit.pending import decide, fold, pending
from cairnkit.writing import Refused, add_fact


def run_list(memory: Memory) -> int:
    items = pending(memory)
    if not items:
        print("No pending auto-candidates.")
        return 0
    print(f"{len(items)} pending auto-candidate(s):")
    for item in items:
        area = item.area or "general"
        print(f"- {item.id} [{item.kind}/{area}] {item.text}")
        print(f"  source {item.source} origin {item.origin}")
    return 0


def run_reject(memory: Memory, cand_id: str, reason: str | None) -> int:
    try:
        decide(memory, cand_id, "dismissed", reason=reason or "Rejected.")
    except KeyError:
        print(f"error: no pending candidate {cand_id}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"rejected {cand_id}")
    return 0


def run_accept(
    memory: Memory,
    cand_id: str,
    *,
    area: str | None,
    basis: str,
    kind: str | None,
    source: str | None,
) -> int:
    states = fold(memory)
    cand = states.get(cand_id)
    if cand is None or cand.status != "pending":
        print(f"error: no pending candidate {cand_id}", file=sys.stderr)
        return 1
    args = SimpleNamespace(
        text=cand.text,
        summary=None,
        kind=kind or cand.kind,
        area=area or cand.area or "general",
        basis=basis,
        source=source or cand.source,
        tag=None,
        happened_at=None,
        link=None,
        pinned=False,
        enforced_by=None,
        supersedes=None,
        reason=None,
        short=False,
        expires=None,
        until_merged=None,
    )
    try:
        fact_id = add_fact(memory, args)
    except Refused as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not fact_id:
        print("error: nothing written (exact repeat of a rule or pinned fact)", file=sys.stderr)
        return 1
    decide(memory, cand_id, "accepted", fact_id=fact_id)
    print(f"accepted {cand_id} as {fact_id}")
    return 0


def run_candidates(memory: Memory, args: argparse.Namespace) -> int:
    if args.candidates_command == "list":
        return run_list(memory)
    if args.candidates_command == "reject":
        return run_reject(memory, args.id, args.reason)
    return run_accept(
        memory,
        args.id,
        area=args.area,
        basis=args.basis,
        kind=args.kind,
        source=args.source,
    )
