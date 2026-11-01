"""`memory add`, `change`, `keep` and `purge`."""

from __future__ import annotations

import contextlib
import secrets
import sys

from cairnkit import followups
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
from cairnkit.similar import analyze, exact_key, possible_conflicts, similarity
from cairnkit.skills import running_tool
from cairnkit.state import effective_status
from cairnkit.store import append_records, drop_id, fact_files

DEFAULT_BASIS = "guess"


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
    with contextlib.suppress(Exception):
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


def _find_similar(memory: Memory, args, moment) -> tuple[dict, float] | None:
    """The best active fact of the same kind and scope that is similar to the new text."""
    scope = _scope(args)
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
    claimed = args.basis
    args.basis = claimed or DEFAULT_BASIS
    args.source = args.source or f"session:{moment.date().isoformat()}"
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
                # No claim was made, and the words are the same, so the older claim still holds.
                args.basis = claimed or old.get("basis", DEFAULT_BASIS)
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
    summary = getattr(args, "summary", None)
    if isinstance(summary, str):
        summary = summary.strip() or None
    if summary and args.kind == "rule":
        print("note: a rule always loads in full, so its --summary is not stored")
        summary = None
    _check_secrets(
        memory, args.text, summary, args.source, args.reason, args.area, *(args.tag or [])
    )
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
        if args.kind != "rule":
            raise Refused("--enforced-by is only for --kind rule")
        fact["enforced_by"] = args.enforced_by
    if args.expires:
        fact["expires_at"] = args.expires
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
        branch = named or current_branch(memory.project.root)
        if not branch and not branch_note:
            raise Refused("--until-merged needs a branch name (HEAD is detached)")
        if branch:
            fact["until_branch_merged"] = branch
            tip = branch_tip(memory.project.root, branch)
            if tip:
                fact["branch_tip"] = tip
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
    _print_conflicts(memory, fact, moment, {supersedes} | ({near[0]["id"]} if near else set()))
    if near:
        old, score = near
        fate = (
            "Both stay active, because a person stated the older one, and an agent task lists "
            "the pair."
            if outranks(old, mine)
            else "An agent task lists the pair, and auto-tidy can supersede the older one."
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
    dropped = sum(drop_id(path, fact_id) for path in fact_files(memory.dir))
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
