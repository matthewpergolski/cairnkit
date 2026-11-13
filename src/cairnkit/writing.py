"""`memory add`, `change`, `keep` and `purge`."""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import stat
import sys
from pathlib import Path, PurePosixPath

from cairnkit import deadline, followups, owner_evidence, plainfile
from cairnkit.autotidy import outranks
from cairnkit.clock import now, parse_time, stamp
from cairnkit.landed import one_work
from cairnkit.memory import Memory
from cairnkit.paths import (
    LINK_NAME,
    branch_exists,
    branch_tip,
    current_branch,
    default_branch,
    merged_checker,
    run_git,
    writer_name,
)
from cairnkit.ranking import PREFIX_MIN, forms, index_words, query_terms
from cairnkit.rule_notices import note_change
from cairnkit.schema import MAX_FILES, RELS, file_problem, stated, validate_record
from cairnkit.secretscan import (
    MASK,
    find_in_record,
    find_secrets,
    has_real_text,
    holds_mask,
    mask,
)
from cairnkit.selection import (
    DATA_LABEL,
    UNCONFIRMED,
    clean,
    clean_path,
    load_text,
    name,
    owner_rule,
    person_said,
)
from cairnkit.similar import analyze, possible_conflicts, repeat_key, similarity
from cairnkit.skills import running_tool
from cairnkit.state import effective_status
from cairnkit.store import append_records, drop_id, drop_line, fact_files, scan, write_lock

DEFAULT_BASIS = "guess"
REASON_WIDTH = 200
# A fact that opens like an order. In a real project "Never list processes with full command
# lines" went in as a plain fact, and the session start held it back.
RULE_START = re.compile(r"(?i)\s*(?:never|always|do not|don['\u2019]t|must)(?![\w-])")
DATA_RULE = (
    "This rule loads as data, because an agent wrote it. "
    "If the owner stated it in this turn, the same command with --basis told lifts it."
)
# Stored as text, a mask would take the place of the true word for good.
MASK_COPY = (
    "this text came from a masked load; write the true text with no value, "
    "or leave the fact as it is."
)


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


def _check_secrets(memory: Memory, *texts: str | None, names: tuple[str | None, ...] = ()) -> None:
    """Refuse a mask or a value that looks secret in each free text that a write stores. A name,
    such as a branch, is read for shapes only, as `find_in_closed_fields` reads it: a branch can
    have the name of a plain word in `.env`."""
    if any(holds_mask(text) for text in texts if text):
        raise Refused(MASK_COPY)
    found = sorted(
        {name for text in texts if text for name in find_secrets(text, memory.env)}
        | {name for text in names if text for name in find_secrets(text)}
    )
    if found:
        raise Refused(
            f"this looks like a secret ({', '.join(found)}); facts must not hold secrets. "
            "Write the fact again and name where the value is, not the value."
        )


def clean_files(root: Path, values: list[str] | None, flag: str = "--files") -> list[str]:
    """The paths of a flag (--files), repo-relative with / between parts, in order and each once.

    A relative path is taken from the repo root. An absolute path must be inside the repo.
    """
    found: list[str] = []
    for value in values or []:
        raw = str(value).strip().replace("\\", "/")
        text = os.path.normpath(raw) if raw else ""
        path = PurePosixPath(text)
        if path.is_absolute():
            for base in (root, root.resolve()):
                with contextlib.suppress(ValueError):
                    path = path.relative_to(base.as_posix())
                    break
        rel = path.as_posix()
        problem = None if text else "is empty"
        if text and (path.is_absolute() or rel == "." or rel.split("/")[0] == ".."):
            problem = "is not inside the repo"
        problem = problem or file_problem(rel)
        if problem:
            raise Refused(f"{flag} {clean(repr(value))}: {problem}. Give paths in the repo.")
        if rel not in found:
            found.append(rel)
    if len(found) > MAX_FILES:
        raise Refused(f"--files names {len(found)} paths; the limit is {MAX_FILES}")
    return found


def _need_fact(memory: Memory, fact_id: str) -> dict:
    state = memory.fact(fact_id)
    if state is None:
        raise Refused(f"no fact with id {clean(mask(fact_id, memory.env))}")
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


def _no_end_event(memory: Memory, fact: dict, cuts: int) -> str | None:
    """Why nothing will end this short note by itself, or None when something will."""
    if fact["scope"] != "short" or fact.get("expires_at"):
        return None
    if not memory.project.is_git:
        return "this folder is not in git"
    branch = fact.get("until_branch_merged")
    if not branch:
        no_answer = deadline.git_cuts() > cuts
        return (
            "git did not answer, so no branch is known" if no_answer else "this is a detached HEAD"
        )
    base = default_branch(memory.project.root)
    if not base:
        return None if deadline.git_cuts() > cuts else "this repo has no default branch"
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


def _retired_match(memory: Memory, args, moment, is_merged) -> tuple[dict, str, str | None] | None:
    """The newest retired fact of the same kind with the new words: (state, status, reason)."""
    key = repeat_key(args.text)
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


_WORD = re.compile(r"[\w'-]+")
_LABEL_AT_END = re.compile(r"\S+\s*[=:]\s*$")


def _keeps_the_words(old: str, new: str) -> bool:
    """Each word of the old text outside a mask is still there, in order. A label can go."""
    kept = [_LABEL_AT_END.sub("", part) for part in MASK.sub("\0", old).split("\0")]
    words = iter(_WORD.findall(new))
    return all(word in words for part in kept for word in _WORD.findall(part))


def _inherit(args, old: dict) -> bool:
    """A clean copy of a masked fact keeps what the fact was. Only a copy keeps a rule's force.

    True when the basis came from the old fact.
    """
    args.kind = old.get("kind", args.kind)
    args.pinned = args.pinned or bool(old.get("pinned"))
    args.area = args.area or old.get("area")
    if old.get("kind") != "rule" or not owner_rule(old):
        args.basis = old.get("basis", args.basis)
        return True
    if _keeps_the_words(str(old.get("text", "")), args.text):
        args.basis = "told"
        return True
    return False


CONFIRM = (
    "To confirm the new fact, quote the owner's words in this turn, or the owner runs the "
    "command from their own shell."
)
# An agent's word does not end a person's: the owner's own words must hold the id.
ENDS = ("expired", "wrong")
ASK_TO_END = (
    'Ask the owner "Shall I end {ids}?" as the last sentence of your message (the fact text can '
    "come before it, in another sentence), and after their yes run: memory change {args} "
    '--status {status} --reason "...". Or the owner types the id, such as "End {first}." Or the '
    "owner runs this command from their own shell."
)


def _told_check(memory: Memory, args) -> owner_evidence.Verdict | None:
    """The check of a `told` claim that an agent makes, or None for no such claim.

    A person at a terminal sets no agent marker, and their word binds as before. A summary loads in
    place of the text, so it must be the owner's words too.
    """
    if args.basis != "told" or not running_tool() or getattr(args, "author", None):
        return None
    verdict = owner_evidence.check_claim(memory, args.text)
    summary = getattr(args, "summary", None)
    shown = isinstance(summary, str) and summary.strip() and args.kind != "rule"
    if verdict.bound and shown and not owner_evidence.check_claim(memory, summary).bound:
        return owner_evidence.Verdict(False, "its --summary is no copy of the owner's words")
    return verdict


def _told_note(verdict: owner_evidence.Verdict, fact: dict) -> str:
    rule = fact["kind"] == "rule"
    if verdict.bound:
        force = " This rule loads as the owner's instruction." if rule else ""
        return f"told: confirmed by {verdict.via}.{force}"
    kind = " --kind rule" if rule else ""
    force = ", and this rule loads as data" if rule else ""
    status = (
        f"told: not confirmed, because {verdict.via}. Saved as {UNCONFIRMED}{force}. Do not say "
        "that it binds."
    )
    if verdict.via == owner_evidence.APPROVAL_ONLY:
        return (
            f"{status} Save the question that the owner said yes to, in this turn: "
            f'memory add "PROPOSAL"{kind} --basis told --supersedes {fact["id"]}'
        )
    return (
        f"{status} Use only the owner's exact words, and put your context in a second fact "
        f"(--basis seen --link related:{fact['id']}). Or the owner runs: "
        f'memory add "TEXT"{kind} --basis told'
    )


def add_fact(memory: Memory, args) -> str | None:
    """Write a fact and return its id. Never refuses a fact for being similar.

    A repeat supersedes the old fact. For a rule or a pinned fact it writes nothing and returns
    None. Inside the write lock the memory is read again, so parallel adds of one text leave one
    active fact. A near repeat is written with a `similar_to` link, and the output says how to
    supersede the old fact. A fact that a person stated (basis `told`) is never superseded by a
    fact with another basis. The new fact is written beside it, linked. The same text as a retired
    fact is written with a link and a note. The same text as a data rule lifts it, when the new
    fact would bind.

    What git adds is read before the lock, because a slow git must not hold the lock.
    """
    moment = now()
    cuts = deadline.git_cuts()
    claimed = args.basis
    args.basis = claimed or DEFAULT_BASIS
    args.source = args.source or f"session:{moment.date().isoformat()}"
    root = memory.project.root
    writer = writer_name(root)
    links = [parse_link(v) for v in args.link or []]
    _check_links(memory, links)
    # Before the lock, because the kind that a masked fact gives decides the checks below.
    masked_target = memory.fact(args.supersedes) if args.supersedes in memory.masked else None
    inherited = bool(masked_target) and _inherit(args, masked_target)
    verdict = None if inherited else _told_check(memory, args)
    # A basis that comes from an older fact keeps whether the owner's words confirmed it.
    unconfirmed = (verdict is not None and not verdict.bound) or (
        inherited and args.basis == "told" and not person_said(masked_target)
    )
    mine = {"basis": args.basis, **({"confirmed": False} if unconfirmed else {})}
    summary = getattr(args, "summary", None)
    if isinstance(summary, str):
        summary = summary.strip() or None
    if summary and args.kind == "rule":
        print("note: a rule always loads in full, so its --summary is not stored")
        summary = None
    _check_secrets(
        memory,
        args.text,
        summary,
        args.source,
        args.reason,
        args.area,
        args.enforced_by,
        *(args.tag or []),
        *(getattr(args, "files", None) or []),
    )
    files = clean_files(memory.project.root, getattr(args, "files", None))
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
            why = "git did not answer" if deadline.git_cuts() > cuts else "HEAD is detached"
            raise Refused(f"--until-merged needs a branch name ({why})")
        _check_secrets(memory, names=(branch,))
        if branch:
            ends["until_branch_merged"] = branch
            tip = branch_tip(root, branch)
            if tip:
                ends["branch_tip"] = tip
    is_merged = merged_checker(root)
    near = None if args.supersedes else _find_similar(memory, args, moment, is_merged)
    retired = _retired_match(memory, args, moment, is_merged)
    with write_lock(memory.dir):
        memory.reload()
        repeat = kept = None
        old = None if args.supersedes else _find_repeat(memory, args, moment, is_merged)
        if old:
            data_rule = old.get("kind") == "rule" and not owner_rule(old)
            lifts = data_rule and owner_rule({"author": running_tool(), **mine})
            if (old.get("kind") == "rule" or old.get("pinned")) and not lifts:
                hint = f" {DATA_RULE}" if data_rule else ""
                if data_rule and verdict and not verdict.bound:
                    hint = f" The told claim is not confirmed, because {verdict.via}.{hint}"
                print(f"already exists: {old['id']} says this. Nothing written.{hint}")
                return None
            near = None
            if outranks(old, mine):
                kept = old
            else:
                repeat = old["id"]
                retired = None
                # No claim was made, and the text is the same, so the older claim still holds.
                if not claimed:
                    args.basis = old.get("basis", DEFAULT_BASIS)
                    unconfirmed = args.basis == "told" and not stated(old)
        supersedes = args.supersedes or repeat
        target = _need_fact(memory, supersedes) if supersedes else None
        if target and target["status"] != "active":
            raise Refused(f"{supersedes} is {target['status']}, not active")
        if target and args.supersedes and not masked_target and outranks(target, mine):
            kept, supersedes = target, None
        if supersedes and target and not files:  # a new text keeps what the fact is about
            files = [str(f) for f in target.get("files") or [] if not holds_mask(str(f))]
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
        if getattr(args, "author", None):
            fact["author"] = args.author
        elif running_tool():
            fact["author"] = f"agent:{running_tool()}"
        if args.tag:
            fact["tags"] = args.tag
        if files:
            fact["files"] = files
        if links:
            fact["links"] = links
        if args.pinned:
            fact["pinned"] = True
        if unconfirmed:
            fact["confirmed"] = False
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
        append_records(memory.writer_file(writer), records, root=memory.dir)
    # First, so that no older ID in a note below reads as the new one.
    print(f"added {fact['id']}")
    _refresh_followups(memory)
    data_rule = fact["kind"] == "rule" and not owner_rule(fact)
    if verdict is not None:
        print(_told_note(verdict, fact))
    elif data_rule:
        print(f"note: {DATA_RULE}")
    if fact["kind"] == "fact" and not args.pinned and RULE_START.match(fact["text"]):
        print(
            "note: this reads as a rule. A plain fact can be held back from the session start; "
            f'a rule loads each time. To make it one: memory add "TEXT" --kind rule '
            f"--supersedes {fact['id']}"
        )
    if fact["kind"] == "rule" and one_work(fact["text"]):
        told = (
            " It replaces this rule only when the owner's words in this turn confirm it (the "
            "told check). If they do not, ask the owner."
            if fact["basis"] == "told"
            else ""
        )
        print(
            "note: this rule reads as approval of one piece of work, and a rule loads in each "
            'session. If it holds only for that work, write it as: memory add "TEXT" --kind '
            f"decision --basis {fact['basis']} --supersedes {fact['id']} with --files PATHS "
            "(tidy proposes the end when each of them has a commit on the main branch) or "
            f"--until-merged BRANCH (it ends at the merge).{told} Keep --kind rule for a lasting "
            "policy."
        )
    if target and supersedes:
        note_change(memory, target, f"replaced by {fact['id']}")
    if not data_rule and not claimed and fact["basis"] == DEFAULT_BASIS:
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
    why = _no_end_event(memory, fact, cuts)
    if memory.project.is_git and deadline.git_cuts() > cuts:
        print(
            f"note: git did not answer in time. This fact went to facts/{writer}.jsonl, and the "
            "checks that need git were skipped."
        )
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
            f"agent task lists the pair. {CONFIRM}"
        )
    if retired:
        old, status, reason = retired
        why = f": {clean(reason)[:REASON_WIDTH]}" if reason else ""
        check = " An agent task asks for a check." if status in ("wrong", "expired") else ""
        print(
            f"note: this text was retired before: {old['id']} ({status}{why}). Written as "
            f"{fact['id']}, linked with similar_to.{check}"
        )
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
            told = stated(old)
            ask = " A person stated it, so ask before you end it." if told else ""
            print(
                f"check: {old['id']} is in the same area and may now be stale ({DATA_LABEL}): "
                f"{clean(load_text(old))}\nIf the new fact replaces it, run: memory change "
                f'{old["id"]} --status superseded --superseded-by {fact["id"]} --reason "..."{ask}'
            )


def change_fact(memory: Memory, args) -> None:
    """Change each fact in args.ids with one set of flags, in one write.

    Each fact gets every check. One refusal writes nothing, so the same command can run again.
    """
    ids = list(dict.fromkeys(args.ids))
    at, writer = stamp(now()), writer_name(memory.project.root)
    records, where = [], ""
    try:
        states = [_need_fact(memory, fact_id) for fact_id in ids]
        # First, because a refusal below can name the value.
        _check_secrets(memory, args.reason, args.enforced_by, names=(args.held_by,))
        _check_not_itself(args, ids)
        told = [s for s in states if _ends_told(args, s)]
        verdict = _check_told(memory, args, [s["id"] for s in told]) if told else None
        for state in states:
            where = f"{state['id']}: "
            records.append(_one_change(memory, args, state, ids, at, writer))
    except Refused as exc:
        if len(ids) == 1:
            raise
        text = str(exc).removesuffix(".")
        raise Refused(f"{where}{text}. No fact changed.") from None
    append_records(memory.writer_file(writer), records, root=memory.dir)
    _refresh_followups(memory)
    for state in states:
        note_change(memory, state, f"status {args.status}" if args.status else "edited")
    for fact_id in ids:
        print(f"changed {fact_id}")
    for state in told:
        print(
            f"told: {state['id']} is {args.status} on the owner's words, confirmed by "
            f"{verdict.via} ({DATA_LABEL}): {clean(load_text(state))}"
        )
    if records[0].get("held_by"):
        for line in _held_by_notes(memory, records[0]["held_by"], states):
            print(line)


def _check_not_itself(args, ids: list[str]) -> None:
    """A fact that this command changes cannot replace it or be its link."""
    targets = [("--superseded-by", args.superseded_by)] if args.superseded_by else []
    targets += [("--link", value) for value in args.link or []]
    for flag, value in targets:
        target = parse_link(value)["id"] if flag == "--link" else value
        if target in ids:
            raise Refused(
                f"{flag} {value} names {target}, a fact that this command changes. A fact cannot "
                "replace itself or link to itself. Name another fact."
            )


def _ends_told(args, state: dict) -> bool:
    """An agent ends a fact that a person stated. Only the owner's own words may do it."""
    return args.status in ENDS and bool(running_tool()) and person_said(state)


def _check_told(memory: Memory, args, told: list[str]) -> owner_evidence.Verdict:
    """The owner's own evidence of this session holds each id in `told`, or nothing changes.
    --reason is the agent's text, so it names nothing here."""
    verdict = owner_evidence.names_ids(memory, told)
    if not verdict.bound:
        raise Refused(
            f"a person stated {', '.join(told)}, so an agent marks such a fact {args.status} only "
            f"when the owner's own words in this session hold its id, and {verdict.via}. "
            + ASK_TO_END.format(
                ids=" and ".join(told),
                args=" ".join(dict.fromkeys(args.ids)),
                status=args.status,
                first=told[0],
            )
        )
    return verdict


def _one_change(memory: Memory, args, state: dict, ids: list[str], at: str, writer: str) -> dict:
    fact_id = state["id"]
    change: dict = {"type": "change", "id": fact_id, "at": at}
    if _ends_told(args, state):
        change["author"] = f"agent:{running_tool()}"
    if args.status:
        change["status"] = args.status
    if args.reason:
        change["reason"] = args.reason
    if args.superseded_by:
        new = _need_fact(memory, args.superseded_by)
        # Like `memory add --supersedes`: an agent's word does not end a person's.
        if running_tool() and person_said(state) and not person_said(new):
            raise Refused(
                f"{fact_id} was stated by a person, and {args.superseded_by} has less authority "
                f"(not stated, or a told claim that the owner's words did not confirm). {CONFIRM}"
            )
        change["superseded_by"] = args.superseded_by
    if args.held_by:
        change["held_by"] = _held_by_path(memory, args, ids)
    links = [parse_link(v) for v in args.link or []]
    _check_links(memory, links)
    if links:
        change["add_links"] = links
    gone = [parse_link(v) for v in getattr(args, "unlink", None) or []]
    for link in gone:
        if link not in state.get("links", []):
            raise Refused(f"{fact_id} has no link {link['rel']}:{link['id']}")
    if gone:
        change["remove_links"] = gone
        # The tool of 0.3.1 knows no remove_links and refuses a change with none of its fields.
        change.setdefault("add_links", [])
    if args.enforced_by:
        if state.get("kind") != "rule":
            raise Refused(f"{fact_id} is a {state.get('kind')}; --enforced-by is only for rules")
        change["enforced_by"] = args.enforced_by
    elif args.no_enforced_by:
        change["enforced_by"] = None
    change["writer"] = writer
    return _validated(change)


def _held_by_path(memory: Memory, args, ids: list[str]) -> str:
    """The repo path of --held-by: a file in the repo that exists now."""
    if args.status != "promoted":
        raise Refused(
            "--held-by needs --status promoted. Run: memory change "
            f'{" ".join(ids)} --status promoted --held-by {args.held_by} --reason "..."'
        )
    [rel] = clean_files(memory.project.root, [args.held_by], flag="--held-by")
    problem = _held_by_problem(memory, rel)
    if problem:
        raise Refused(f"--held-by {rel!r} {problem}. Name the repo file that holds the rule.")
    return rel


def _held_by_problem(memory: Memory, rel: str) -> str | None:
    """Why the repo path rel is no file for held_by, or None. The check uses the real path, so a
    link cannot lead out of the repo, into .git or into the memory."""
    root = memory.project.root.resolve()
    try:
        real = (root / rel).resolve()
    except (OSError, RuntimeError):
        return "cannot be read"
    memory_dir = memory.dir.resolve()
    if PurePosixPath(rel).parts[0] == LINK_NAME or memory_dir in (real, *real.parents):
        return "is in the memory folder"
    if root not in real.parents:
        return "leads outside the repo"
    if ".git" in (*PurePosixPath(rel).parts, *real.relative_to(root).parts):
        return "is in .git"
    try:
        mode = os.stat(real).st_mode
    except OSError:
        return "does not exist"
    if stat.S_ISDIR(mode):
        return "is a folder"
    return None if stat.S_ISREG(mode) else "is no regular file"


HELD_BY_READ = 1_000_000  # the bytes of each file that the word check of held_by reads
HELD_BY_PEERS = 50  # the other files that it reads to find the right one


def _file_words(path: Path) -> set[str]:
    """The search words of a regular file. A pipe or a device is no such file, so no read waits."""
    try:
        with os.fdopen(plainfile.open_fd(path), "rb") as fh:
            return set(index_words(fh.read(HELD_BY_READ).decode("utf-8", "replace")))
    except OSError:
        return set()


def _key_terms(state: dict) -> list[str]:
    """The words of a fact that a file that holds it is likely to hold too."""
    return [t for t in query_terms(str(state.get("text", ""))) if len(t) >= PREFIX_MIN]


def _holds(words: set[str], terms: list[str]) -> int:
    return sum(not words.isdisjoint(forms(term)) for term in terms)


def _held_by_notes(memory: Memory, rel: str, states: list[dict]) -> list[str]:
    """Notes, not refusals. A typo of a real file makes a promoted fact a dead end, so a file that
    holds no key word of the fact gets a note that names a file that holds them."""
    from cairnkit.ignore import is_tracked

    project, notes = memory.project, []
    if project.is_git and not is_tracked(project, rel):
        notes.append(
            f"note: git does not track {rel}. Commit it, or other checkouts do not have the rule."
        )
    words = _file_words(project.root / rel)
    lost = [(s["id"], t) for s in states if (t := _key_terms(s)) and not _holds(words, t)]
    if not lost:
        return notes
    ids = " ".join(fact_id for fact_id, _ in lost)
    best, score = None, 0
    for peer in _held_by_peers(memory, rel):
        found = _file_words(project.root / peer)
        got = sum(_holds(found, terms) for _, terms in lost)
        if got > score:
            best, score = peer, got
    hint = (
        f"{best} holds them. If it holds the rule, run: memory change {ids} --status promoted "
        f'--held-by {best} --reason "..."'
        if best
        else "Check the path."
    )
    notes.append(f"note: {rel} holds none of the key words of {ids}. {hint}")
    return notes


def _held_by_peers(memory: Memory, rel: str) -> list[str]:
    """The other files in the folder of rel, then the tracked files with its name. Each one is a
    file that --held-by takes."""
    project, path = memory.project, PurePosixPath(rel)
    found: list[str] = []
    with contextlib.suppress(OSError):
        for entry in sorted(os.scandir(project.root / path.parent), key=lambda e: e.name):
            if entry.is_file():
                found.append((path.parent / entry.name).as_posix())
    if project.is_git:
        listed = run_git(project.root, "ls-files", "-z", "--", f"*{path.name}", timeout=2.0)
        found += [p for p in (listed or "").split("\0") if PurePosixPath(p).name == path.name]
    # A name that does not print could steer the terminal, and no --held-by takes it.
    names = [p for p in dict.fromkeys(found) if p != rel and not file_problem(p)][:HELD_BY_PEERS]
    return [p for p in names if not _held_by_problem(memory, p)]


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
    append_records(memory.writer_file(change["writer"]), [_validated(change)], root=memory.dir)


_ID_IN_LINE = re.compile(r'"id"\s*:\s*"([^"]+)"')


def _says_secret(reason: str, yes: bool) -> bool:
    return yes and reason.strip().lower() == "secret"


def _line_route(what: str, ref: str) -> str:
    return (
        f"purge removes {what} for good, and it can hold true text. `memory check` names the way "
        f"to read it. Write again what is true, then run memory purge {ref} --reason secret --yes"
    )


def _can_end_a_true_fact(memory: Memory, fact_id: str, reason: str, yes: bool) -> None:
    """Purge is the one thing that loses text, and a fact with a mask can hold true text."""
    state = memory.states[fact_id]
    replaced = state.get("status") == "superseded" and memory.fact(state.get("superseded_by", ""))
    if replaced or not has_real_text(str(state.get("text", ""))):
        return
    if _says_secret(reason, yes):
        return
    raise Refused(
        f"{fact_id} holds true text beyond the value that looks secret ({DATA_LABEL}): "
        f"{clean(state.get('text'))}\n"
        f'Write what is true first: memory add "TEXT" --supersedes {fact_id}. Then purge it. '
        "If nothing in it is true, purge it with --reason secret --yes."
    )


def _write_tombstone(memory: Memory, fact_id: str, reason: str) -> None:
    tomb = {
        "type": "tombstone",
        "id": fact_id,
        "at": stamp(now()),
        "reason": reason,
        "writer": writer_name(memory.project.root),
    }
    append_records(memory.writer_file(tomb["writer"]), [_validated(tomb)], root=memory.dir)
    _refresh_followups(memory)


def _purge_line(memory: Memory, ref: str, reason: str, yes: bool) -> int:
    line = next((line for line in memory.secret_lines if line.ref == ref), None)
    if line is None:
        raise Refused(
            f"no line with a value that looks secret is {ref}. `memory check` names each."
        )
    if not _says_secret(reason, yes):
        raise Refused(_line_route("this line", ref))
    dropped = drop_line(memory.dir, line.sha)
    _write_tombstone(memory, ref, reason)
    return dropped


def purge_fact(memory: Memory, fact_id: str, reason: str, yes: bool) -> int:
    """Remove every line for fact_id and leave a tombstone. The only real deletion."""
    if find_secrets(fact_id, memory.env):
        raise Refused(
            "this looks like a secret, so it is no id, and nothing was written. "
            "`memory check` names each record by its id or by `line-` and a hash."
        )
    _check_secrets(memory, reason)
    if fact_id.startswith("line-"):
        return _purge_line(memory, fact_id, reason, yes)
    located, bad = scan(fact_files(memory.dir))
    lines = [item.record for item in located if item.record.get("id") == fact_id]
    torn = [item for item in bad if fact_id in _ID_IN_LINE.findall(item.text)]
    if not lines and not torn:
        raise Refused(f"no record with id {clean(fact_id)}")
    holds_text = torn or any(
        rec.get("type") != "tombstone" or find_in_record(rec, memory.env) for rec in lines
    )
    if not holds_text:
        raise Refused(f"{fact_id} is already purged")
    if fact_id in memory.masked:
        _can_end_a_true_fact(memory, fact_id, reason, yes)
    if any(find_secrets(item.text, memory.env) for item in torn) and not _says_secret(reason, yes):
        raise Refused(_line_route(f"this torn line of {fact_id}", fact_id))
    if not yes:
        raise Refused(
            f"purge removes {fact_id} for good and cannot be undone. "
            "To forget a fact, use `memory change ID --status expired|wrong`. "
            "Run again with --yes to purge."
        )
    before = memory.states.get(fact_id, {})
    dropped = drop_id(memory.dir, fact_id)
    _write_tombstone(memory, fact_id, reason)
    # A purge often removes a secret, so its notice holds no text.
    note_change(memory, {**before, "text": None}, "purged")
    return dropped


def fail(message: str) -> int:
    print(f"error: {clean_path(message)}", file=sys.stderr)
    return 1


def check_time_arg(value: str) -> str:
    parse_time(value)
    return value
