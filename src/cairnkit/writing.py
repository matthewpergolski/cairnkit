"""`memory add`, `change`, `keep` and `purge`."""

from __future__ import annotations

import contextlib
import secrets
import sys
from datetime import timedelta

from cairnkit import followups
from cairnkit.autotidy import outranks
from cairnkit.clock import now, parse_time, stamp
from cairnkit.memory import Memory
from cairnkit.paths import current_branch, merged_checker, writer_name
from cairnkit.schema import RELS, validate_record
from cairnkit.secretscan import find_secrets
from cairnkit.selection import clean
from cairnkit.similar import analyze, exact_key, similarity
from cairnkit.skills import running_tool
from cairnkit.state import effective_status
from cairnkit.store import append_records, drop_id, fact_files


class Refused(Exception):
    """The input breaks a rule. Nothing was written."""


def parse_link(value: str) -> dict:
    rel, sep, target = value.partition(":")
    if not sep or rel not in RELS or not target:
        raise Refused(f"link {value!r} must be <rel>:<id>, rel one of {', '.join(RELS)}")
    return {"rel": rel, "id": target}


def _new_id(memory: Memory, day: str) -> str:
    for _ in range(1000):
        candidate = f"f-{day}-{secrets.token_hex(2)}"
        if candidate not in memory.states:
            return candidate
    raise Refused(f"no free id left for {day}")


def _check_secrets(*texts: str | None) -> None:
    found = sorted({name for text in texts if text for name in find_secrets(text)})
    if found:
        raise Refused(f"this looks like a secret ({', '.join(found)}); facts must not hold secrets")


def _need_fact(memory: Memory, fact_id: str) -> dict:
    state = memory.fact(fact_id)
    if state is None:
        raise Refused(f"no fact with id {fact_id}")
    return state


def _check_links(memory: Memory, links: list[dict]) -> None:
    for link in links:
        _need_fact(memory, link["id"])


def _validated(record: dict) -> dict:
    problems = validate_record(record)
    if problems:
        raise Refused("; ".join(problems))
    return record


def _refresh_followups(memory: Memory) -> None:
    """Keep the tidy task file true to the facts. A failure here never fails a write."""
    with contextlib.suppress(Exception):
        memory.reload()
        followups.refresh(memory)


def _find_similar(memory: Memory, args, moment) -> tuple[dict, float] | None:
    """The best active fact of the same kind and scope that is similar to the new text."""
    scope = "short" if args.short or args.until_merged is not None else "long"
    words = analyze(args.text)
    is_merged = merged_checker(memory.project.root)
    best: tuple[float, str, dict] | None = None  # (score, learned_at, state)
    for state in memory.states.values():
        if state.get("status") == "purged" or state.get("kind", "fact") != args.kind:
            continue
        if state["scope"] != scope or effective_status(state, moment, is_merged)[0] != "active":
            continue
        score = similarity(words, analyze(state.get("text", "")))
        if score is not None and (best is None or (score, state.get("learned_at", "")) > best[:2]):
            best = (score, state.get("learned_at", ""), state)
    return None if best is None else (best[2], best[0])


def _retired_match(memory: Memory, args, moment) -> tuple[dict, str, str | None] | None:
    """The newest retired fact of the same kind with the new words: (state, status, reason)."""
    key = exact_key(args.text)
    is_merged = merged_checker(memory.project.root)
    best = None
    for state in memory.states.values():
        if state.get("status") == "purged" or state.get("kind", "fact") != args.kind:
            continue
        status, reason = effective_status(state, moment, is_merged)
        if status not in ("expired", "wrong", "superseded") or key != exact_key(state["text"]):
            continue
        if best is None or (state.get("learned_at", ""), state["id"]) > best[0]:
            best = ((state.get("learned_at", ""), state["id"]), state, status, reason)
    return None if best is None else best[1:]


def add_fact(memory: Memory, args) -> str | None:
    """Write a fact and return its id. Never refuses a fact for being similar.

    An exact repeat supersedes the old fact. For a rule or a pinned fact it
    writes nothing and returns None. A near repeat is written with a
    `similar_to` link, and the output says how to supersede the old fact.
    A fact that a person stated (basis `told`) is never superseded by a fact
    with another basis. The new fact is written beside it, linked. The same
    words as a retired fact are written with a link and a note.
    """
    moment = now()
    repeat = near = kept = None
    mine = {"basis": args.basis}
    if not args.supersedes:
        match = _find_similar(memory, args, moment)
        if match and match[1] == 1.0:
            old = match[0]
            if old.get("kind") == "rule" or old.get("pinned"):
                print(f"already exists: {old['id']} says this. Nothing written.")
                return None
            if outranks(old, mine):
                kept = old
            else:
                repeat = old["id"]
        elif match:
            near = match
    writer = writer_name(memory.project.root)
    links = [parse_link(v) for v in args.link or []]
    _check_links(memory, links)
    supersedes = args.supersedes or repeat
    target = _need_fact(memory, supersedes) if supersedes else None
    if target and target["status"] != "active":
        raise Refused(f"{supersedes} is {target['status']}, not active")
    if target and args.supersedes and outranks(target, mine):
        kept, supersedes = target, None
    retired = None if repeat else _retired_match(memory, args, moment)
    for other in (near[0] if near else None, kept, retired[0] if retired else None):
        if other and {"rel": "similar_to", "id": other["id"]} not in links:
            links.append({"rel": "similar_to", "id": other["id"]})
    _check_secrets(args.text, args.source, args.reason, *(args.tag or []))
    fact = {
        "type": "fact",
        "id": _new_id(memory, moment.strftime("%Y%m%d")),
        "kind": args.kind,
        "text": args.text.strip(),
        "area": args.area,
        "happened_at": args.happened_at or moment.date().isoformat(),
        "learned_at": stamp(moment),
        "source": args.source,
        "basis": args.basis,
        "status": "active",
        "scope": "short" if args.short else "long",
        "writer": writer,
    }
    if running_tool():
        fact["author"] = f"agent:{running_tool()}"
    if args.tag:
        fact["tags"] = args.tag
    if links:
        fact["links"] = links
    if args.pinned:
        fact["pinned"] = True
    if args.enforced_by:
        if args.kind != "rule":
            raise Refused("--enforced-by is only for --kind rule")
        fact["enforced_by"] = args.enforced_by
    if args.short or args.expires:
        if args.expires:
            fact["expires_at"] = args.expires
        elif args.until_merged is None:
            days = memory.config["short_term_days"]
            fact["expires_at"] = stamp(moment + timedelta(days=days))
    if args.until_merged is not None:
        fact["scope"] = "short"
        if not memory.project.is_git:
            raise Refused(
                "--until-merged needs a git repo, and this folder is not in one. "
                "Use --short (and --expires DATE) instead."
            )
        branch = args.until_merged or current_branch(memory.project.root)
        if not branch:
            raise Refused("--until-merged needs a branch name (HEAD is detached)")
        fact["until_branch_merged"] = branch
    records = [_validated(fact)]
    if supersedes:
        change = {
            "type": "change",
            "id": supersedes,
            "at": stamp(moment),
            "status": "superseded",
            "superseded_by": fact["id"],
            "reason": args.reason or f"Replaced by {fact['id']}.",
            "writer": writer,
        }
        records.append(_validated(change))
    append_records(memory.writer_file(writer), records)
    _refresh_followups(memory)
    if repeat:
        print(f"superseded {repeat}: the new fact has the same words")
    if kept:
        print(
            f"not superseded: {kept['id']} was stated by a person (basis told), and the new fact "
            f"is not. Written as {fact['id']}, linked with similar_to. Both stay active and an "
            "agent task lists the pair."
        )
    if retired:
        old, status, reason = retired
        why = f": {clean(reason)}" if reason else ""
        check = " An agent task asks for a check." if status in ("wrong", "expired") else ""
        print(
            f"note: this text was retired before: {old['id']} ({status}{why}). Written as "
            f"{fact['id']}, linked with similar_to.{check}"
        )
    if near:
        old, score = near
        print(
            f"similar to {old['id']} ({score:.0%} the same words): {old.get('text')}\n"
            f"Both stay active and an agent task lists the pair. To replace it, run: "
            f"memory change {old['id']} --status superseded --superseded-by {fact['id']} "
            f'--reason "..."'
        )
    return fact["id"]


def change_fact(memory: Memory, args) -> None:
    state = _need_fact(memory, args.id)
    moment = now()
    change: dict = {"type": "change", "id": args.id, "at": stamp(moment)}
    if args.status:
        change["status"] = args.status
    if args.reason:
        change["reason"] = args.reason
    if args.superseded_by:
        _need_fact(memory, args.superseded_by)
        change["superseded_by"] = args.superseded_by
    if args.held_by:
        if not (memory.project.root / args.held_by).exists():
            raise Refused(f"held_by {args.held_by!r} does not exist in {memory.project.root}")
        change["held_by"] = args.held_by
    links = [parse_link(v) for v in args.link or []]
    _check_links(memory, links)
    if links:
        change["add_links"] = links
    if args.enforced_by:
        if state.get("kind") != "rule":
            raise Refused(f"{args.id} is a {state.get('kind')}; --enforced-by is only for rules")
        change["enforced_by"] = args.enforced_by
    elif args.no_enforced_by:
        change["enforced_by"] = None
    _check_secrets(args.reason)
    change["writer"] = writer_name(memory.project.root)
    append_records(memory.writer_file(change["writer"]), [_validated(change)])
    _refresh_followups(memory)


def keep_fact(memory: Memory, fact_id: str, reason: str | None) -> None:
    state = _need_fact(memory, fact_id)
    if state.get("scope", "long") == "long":
        raise Refused(f"{fact_id} is already long-term")
    _check_secrets(reason)
    change = {
        "type": "change",
        "id": fact_id,
        "at": stamp(now()),
        "scope": "long",
        "reason": reason or "Kept as long-term.",
        "writer": writer_name(memory.project.root),
    }
    append_records(memory.writer_file(change["writer"]), [_validated(change)])


def purge_fact(memory: Memory, fact_id: str, reason: str, yes: bool) -> int:
    """Remove every line for fact_id and leave a tombstone. The only real deletion."""
    if fact_id not in memory.states and not any(
        fact_id in path.read_text(encoding="utf-8") for path in fact_files(memory.dir)
    ):
        raise Refused(f"no record with id {fact_id}")
    if memory.states.get(fact_id, {}).get("status") == "purged":
        raise Refused(f"{fact_id} is already purged")
    if not yes:
        raise Refused(
            f"purge removes {fact_id} for good and cannot be undone. "
            "To forget a fact, use `memory change ID --status expired|wrong`. "
            "Run again with --yes to purge."
        )
    _check_secrets(reason)
    dropped = sum(drop_id(path, fact_id) for path in fact_files(memory.dir))
    tomb = {
        "type": "tombstone",
        "id": fact_id,
        "at": stamp(now()),
        "reason": reason,
        "writer": writer_name(memory.project.root),
    }
    append_records(memory.writer_file(tomb["writer"]), [_validated(tomb)])
    return dropped


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def check_time_arg(value: str) -> str:
    parse_time(value)
    return value
