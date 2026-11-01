"""`memory add`, `change`, `keep` and `purge`."""

from __future__ import annotations

import contextlib
import secrets
import sys

from cairnkit import deadline, followups
from cairnkit.autotidy import outranks
from cairnkit.clock import now, parse_time, stamp
from cairnkit.memory import Memory
from cairnkit.paths import (
    branch_exists,
    branch_tip,
    current_branch,
    default_branch,
    merged_checker,
    writer_name,
)
from cairnkit.schema import RELS, validate_record
from cairnkit.secretscan import find_in_record, find_secrets
from cairnkit.selection import DATA_LABEL, clean, load_text, name
from cairnkit.similar import analyze, possible_conflicts, repeat_key, similarity
from cairnkit.skills import running_tool
from cairnkit.state import effective_status
from cairnkit.store import append_records, drop_id, fact_files, write_lock

DEFAULT_BASIS = "guess"
# What git adds to a write is a note. With a slow git, the fact still lands in a tool's time limit.
LOOK_BUDGET = 3.0


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


def _check_secrets(memory: Memory, *texts: str | None) -> None:
    found = sorted({name for text in texts if text for name in find_secrets(text, memory.env)})
    if found:
        raise Refused(
            f"this looks like a secret ({', '.join(found)}); facts must not hold secrets. "
            "Write the fact again and name where the value is, not the value."
        )


def _need_fact(memory: Memory, fact_id: str) -> dict:
    if fact_id in memory.withheld:
        raise Refused(memory.withheld_note(fact_id))
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
    with contextlib.suppress(Exception), deadline.within(LOOK_BUDGET):
        memory.reload()
        followups.refresh(memory)


def _scope(args) -> str:
    """An end date or an end branch makes a note short-term, with or without --short."""
    return "short" if args.short or args.expires or args.until_merged is not None else "long"


def _no_end_event(memory: Memory, fact: dict) -> str | None:
    """Why nothing will end this short note by itself, or None when something will."""
    if fact["scope"] != "short" or fact.get("expires_at"):
        return None
    if not memory.project.is_git:
        return "this folder is not in git"
    branch = fact.get("until_branch_merged")
    if not branch:
        return "this is a detached HEAD"
    base = default_branch(memory.project.root)
    if not base:
        return "this repo has no default branch"
    return f"{branch} is the default branch" if branch == base else None


def _is_peer(state: dict, args, moment, is_merged) -> bool:
    """An active fact of the same kind and scope as the new one."""
    return (
        state.get("status") != "purged"
        and state.get("kind", "fact") == args.kind
        and state["scope"] == _scope(args)
        and effective_status(state, moment, is_merged)[0] == "active"
    )


def _find_repeat(memory: Memory, args, moment, is_merged) -> dict | None:
    """The newest active fact of the same kind and scope that has the same text."""
    key = repeat_key(args.text)
    same = [
        state
        for state in memory.states.values()
        if repeat_key(state.get("text", "")) == key and _is_peer(state, args, moment, is_merged)
    ]
    return max(same, key=lambda state: state.get("learned_at", ""), default=None)


def _find_similar(memory: Memory, args, moment, is_merged) -> tuple[dict, float] | None:
    """The best active fact of the same kind and scope with similar words, not the same text."""
    key = repeat_key(args.text)
    words = analyze(args.text)
    best: tuple[tuple, dict] | None = None  # (score, learned_at), state
    for state in memory.states.values():
        text = state.get("text", "")
        score = None if repeat_key(text) == key else similarity(words, analyze(text))
        if score is None or not _is_peer(state, args, moment, is_merged):
            continue
        rank = (score, state.get("learned_at", ""))
        if best is None or rank > best[0]:
            best = (rank, state)
    return None if best is None else (best[1], best[0][0])


def _retired_match(memory: Memory, args, moment) -> tuple[dict, str, str | None] | None:
    """The newest retired fact of the same kind with the new words: (state, status, reason)."""
    key = repeat_key(args.text)
    is_merged = merged_checker(memory.project.root)
    best = None
    for state in memory.states.values():
        if state.get("status") == "purged" or state.get("kind", "fact") != args.kind:
            continue
        status, reason = effective_status(state, moment, is_merged)
        if status not in ("expired", "wrong", "superseded") or key != repeat_key(state["text"]):
            continue
        if best is None or (state.get("learned_at", ""), state["id"]) > best[0]:
            best = ((state.get("learned_at", ""), state["id"]), state, status, reason)
    return None if best is None else best[1:]


def add_fact(memory: Memory, args) -> str | None:
    """Write a fact and return its id. Never refuses a fact for being similar.

    A repeat supersedes the old fact. For a rule or a pinned fact it writes nothing and returns
    None. Inside the write lock the memory is read again, so parallel adds of one text leave one
    active fact. A near repeat is written with a `similar_to` link, and the output says how to
    supersede the old fact. A fact that a person stated (basis `told`) is never superseded by a
    fact with another basis. The new fact is written beside it, linked. The same text as a retired
    fact is written with a link and a note.

    What git adds is read before the lock, because a slow git must not hold the lock.
    """
    moment = now()
    claimed = args.basis
    args.basis = claimed or DEFAULT_BASIS
    args.source = args.source or f"session:{moment.date().isoformat()}"
    mine = {"basis": args.basis}
    root = memory.project.root
    writer = writer_name(root)
    links = [parse_link(v) for v in args.link or []]
    _check_links(memory, links)
    summary = getattr(args, "summary", None)
    if isinstance(summary, str):
        summary = summary.strip() or None
    if summary and args.kind == "rule":
        print("note: a rule always loads in full, so its --summary is not stored")
        summary = None
    _check_secrets(
        memory, args.text, summary, args.source, args.reason, args.area, *(args.tag or [])
    )
    if args.enforced_by and args.kind != "rule":
        raise Refused("--enforced-by is only for --kind rule")
    ends: dict = {}
    if args.expires:
        ends["expires_at"] = args.expires
    branch_note = args.short and not args.expires and memory.project.is_git
    if args.until_merged is None and branch_note:
        args.until_merged = ""  # A short note ends with its branch. The clock alone ends nothing.
    if args.until_merged is not None:
        if not memory.project.is_git:
            raise Refused(
                "--until-merged needs a git repo, and this folder is not in one. "
                "Use --short (and --expires DATE) instead."
            )
        named = "" if args.until_merged == "HEAD" else args.until_merged
        branch = named or current_branch(root)
        if not branch and not branch_note:
            raise Refused("--until-merged needs a branch name (HEAD is detached)")
        if branch:
            ends["until_branch_merged"] = branch
            tip = branch_tip(root, branch)
            if tip:
                ends["branch_tip"] = tip
    is_merged = merged_checker(root)
    near = None if args.supersedes else _find_similar(memory, args, moment, is_merged)
    retired = _retired_match(memory, args, moment)
    with write_lock(memory.dir):
        memory.reload()
        repeat = kept = None
        old = None if args.supersedes else _find_repeat(memory, args, moment, is_merged)
        if old:
            if old.get("kind") == "rule" or old.get("pinned"):
                print(f"already exists: {old['id']} says this. Nothing written.")
                return None
            near = None
            if outranks(old, mine):
                kept = old
            else:
                repeat = old["id"]
                retired = None
                # No claim was made, and the text is the same, so the older claim still holds.
                args.basis = claimed or old.get("basis", DEFAULT_BASIS)
        supersedes = args.supersedes or repeat
        target = _need_fact(memory, supersedes) if supersedes else None
        if target and target["status"] != "active":
            raise Refused(f"{supersedes} is {target['status']}, not active")
        if target and args.supersedes and outranks(target, mine):
            kept, supersedes = target, None
        for other in (near[0] if near else None, kept, retired[0] if retired else None):
            if other and {"rel": "similar_to", "id": other["id"]} not in links:
                links.append({"rel": "similar_to", "id": other["id"]})
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
            "scope": _scope(args),
            "writer": writer,
        }
        if summary:
            fact["summary"] = summary
        if running_tool():
            fact["author"] = f"agent:{running_tool()}"
        if args.tag:
            fact["tags"] = args.tag
        if links:
            fact["links"] = links
        if args.pinned:
            fact["pinned"] = True
        if args.enforced_by:
            fact["enforced_by"] = args.enforced_by
        fact.update(ends)
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
    if not claimed and fact["basis"] == DEFAULT_BASIS:
        print(
            f"note: saved with basis {DEFAULT_BASIS}, the default. Add --basis seen if you "
            "observed it, or --basis told if a person said it."
        )
    branch = fact.get("until_branch_merged")
    if branch and not branch_exists(memory.project.root, branch):
        print(
            f"note: no branch {name(branch)} exists here, local or remote. Check the name. "
            "This note stays open until that branch appears and merges. To end it yourself, run: "
            f'memory change {fact["id"]} --status expired --reason "..."'
        )
    why = _no_end_event(memory, fact)
    if why:
        print(
            f"note: no end event for this short note, because {why}. End it yourself: "
            f'memory change {fact["id"]} --status expired --reason "..."'
        )
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
    with deadline.within(LOOK_BUDGET):
        _print_conflicts(memory, fact, moment, {supersedes} | ({near[0]["id"]} if near else set()))
    if near:
        old, score = near
        if outranks(old, mine):
            fate = (
                "Both stay active, because a person stated the older one, and an agent task "
                "lists the pair."
            )
        else:
            fate = (
                "Both stay active, because a differing word can make a different fact, and an "
                "agent task lists the pair."
            )
        print(
            f"similar to {old['id']} ({score:.0%} the same words; {DATA_LABEL}): "
            f"{clean(old.get('text'))}\n"
            f"{fate} To replace it now, run: "
            f"memory change {old['id']} --status superseded --superseded-by {fact['id']} "
            f'--reason "..."'
        )
    return fact["id"]


def _print_conflicts(memory: Memory, fact: dict, moment, skip: set) -> None:
    """Name older facts that the new one may replace. The agent decides. Nothing ends here."""
    is_merged = merged_checker(memory.project.root)
    with contextlib.suppress(Exception):
        memory.reload()
        for old in possible_conflicts(memory, fact, moment, is_merged):
            if old["id"] in skip:
                continue
            told = old.get("basis") == "told"
            ask = " A person stated it, so ask before you end it." if told else ""
            print(
                f"check: {old['id']} is in the same area and may now be stale ({DATA_LABEL}): "
                f"{clean(load_text(old))}\nIf the new fact replaces it, run: memory change "
                f'{old["id"]} --status superseded --superseded-by {fact["id"]} --reason "..."{ask}'
            )


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
        if args.status != "promoted":
            raise Refused(
                "--held-by needs --status promoted. Run: memory change "
                f'{args.id} --status promoted --held-by {args.held_by} --reason "..."'
            )
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
    _check_secrets(memory, args.reason)
    change["writer"] = writer_name(memory.project.root)
    append_records(memory.writer_file(change["writer"]), [_validated(change)])
    _refresh_followups(memory)


def keep_fact(memory: Memory, fact_id: str, reason: str | None) -> None:
    state = _need_fact(memory, fact_id)
    if state.get("scope", "long") == "long":
        raise Refused(f"{fact_id} is already long-term")
    _check_secrets(memory, reason)
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
        fact_id.encode() in path.read_bytes() for path in fact_files(memory.dir)
    ):
        raise Refused(f"no record with id {fact_id}")
    tomb = memory.states.get(fact_id, {})
    if tomb.get("status") == "purged" and not find_in_record(tomb, memory.env):
        raise Refused(f"{fact_id} is already purged")
    if not yes:
        raise Refused(
            f"purge removes {fact_id} for good and cannot be undone. "
            "To forget a fact, use `memory change ID --status expired|wrong`. "
            "Run again with --yes to purge."
        )
    _check_secrets(memory, reason)
    dropped = drop_id(memory.dir, fact_id)
    tomb = {
        "type": "tombstone",
        "id": fact_id,
        "at": stamp(now()),
        "reason": reason,
        "writer": writer_name(memory.project.root),
    }
    append_records(memory.writer_file(tomb["writer"]), [_validated(tomb)])
    _refresh_followups(memory)
    return dropped


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def check_time_arg(value: str) -> str:
    parse_time(value)
    return value
