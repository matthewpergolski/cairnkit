"""`memory check`: report every problem in the memory and its links."""

from __future__ import annotations

import json
from collections import Counter

from cairnkit import instruction_files, presets, skills
from cairnkit.clock import now
from cairnkit.init import ensure_all_linked
from cairnkit.memory import Memory
from cairnkit.paths import LINK_NAME, Project, merged_checker, resolve_memory_dir
from cairnkit.schema import validate_record
from cairnkit.secretscan import find_secrets
from cairnkit.state import effective_status
from cairnkit.store import fact_files, read_located


def _repair_cmd(memdir) -> str:
    """The command that links a checkout to memdir. Never bare init when memory exists."""
    if memdir.is_dir():
        return f"`memory init --path {memdir}`"
    return "`memory init`"


def check_links(project: Project, memdir) -> list[str]:
    errors = []
    repair = _repair_cmd(memdir)
    for checkout in project.checkouts:
        link = checkout / LINK_NAME
        if link.is_symlink():
            if not link.exists():
                errors.append(f"{link}: broken link; run {repair} to relink it")
            elif link.resolve() != memdir.resolve():
                errors.append(
                    f"{link}: points to {link.resolve()}, not {memdir}; run {repair} to relink it"
                )
        elif link.is_dir():
            errors.append(
                f"{link}: a real folder, not a link; move its files to {memdir / 'notes'}/, "
                f"remove the folder, then run {repair}"
            )
        elif link.exists():
            errors.append(f"{link}: a file, not a link; move it away, then run {repair}")
        else:
            errors.append(f"{link}: missing; run {repair} from {checkout}")
    return errors


def check_records(memory: Memory) -> tuple[list[str], list[str]]:
    located, errors = read_located(fact_files(memory.dir))
    warnings: list[str] = []
    ids = Counter(item.record.get("id") for item in located if item.record.get("type") == "fact")
    known = {i for i in ids if i} | {
        item.record.get("id") for item in located if item.record.get("type") == "tombstone"
    }
    kinds = {
        item.record.get("id"): item.record.get("kind")
        for item in located
        if item.record.get("type") == "fact"
    }
    for item in located:
        rec, where = item.record, f"{item.path.name}:{item.line}"
        problems = list(validate_record(rec))
        raw = json.dumps(rec, ensure_ascii=False)
        problems += [f"looks like a secret ({name})" for name in find_secrets(raw)]
        kind = rec.get("type")
        if kind == "fact" and ids[rec.get("id")] > 1:
            problems.append(f"duplicate id {rec.get('id')}")
        if kind == "change" and rec.get("id") not in known:
            problems.append(f"change names an unknown fact {rec.get('id')}")
        target = rec.get("superseded_by")
        if target and target not in known:
            problems.append(f"superseded_by {target} is not a known fact")
        for link in rec.get("links", []) + rec.get("add_links", []):
            if isinstance(link, dict) and link.get("id") not in known:
                problems.append(f"link to unknown fact {link.get('id')}")
        if kind == "change" and rec.get("enforced_by") and kinds.get(rec.get("id")) != "rule":
            problems.append("enforced_by is only for kind 'rule'")
        held = rec.get("held_by")
        if held and not (memory.project.root / held).exists():
            problems.append(f"held_by {held} does not exist")
        writer = rec.get("writer")
        if writer and writer != item.path.stem and kind != "tombstone":
            warnings.append(f"{where}: writer {writer!r} differs from the file name")
        errors += [f"{where}: {problem}" for problem in problems]
    return errors, warnings


DUPLICATES_DOC = (
    "https://github.com/matthewpergolski/cairnkit/blob/main/docs/layering.md#if-you-have-duplicates"
)


def duplicate_rules(memory: Memory) -> list[str]:
    """Warnings for active rules that an instruction file already says, word for word."""
    found = instruction_files.items(memory.project.root)
    if not found:
        return []
    moment, is_merged = now(), merged_checker(memory.project.root)
    warnings = []
    for state in sorted(memory.states.values(), key=lambda s: s.get("learned_at", "")):
        if state.get("kind") != "rule":
            continue
        if effective_status(state, moment, is_merged)[0] != "active":
            continue
        item = instruction_files.home(found, str(state.get("text", "")))
        if item:
            warnings.append(
                f"{item.file}:{item.line}: repeats rule fact {state['id']}; keep one copy "
                f"(see {DUPLICATES_DOC})"
            )
    return warnings


def advisory_rules(memory: Memory) -> list[str]:
    """Active rules that no check enforces: they are prose only."""
    moment, is_merged = now(), merged_checker(memory.project.root)
    lines = []
    for state in sorted(memory.states.values(), key=lambda s: s.get("learned_at", "")):
        if state.get("kind") != "rule" or state.get("enforced_by"):
            continue
        if effective_status(state, moment, is_merged)[0] == "active":
            lines.append(f"- [{state['id']}] {state.get('text', '')}")
    return lines


# Rules are loaded in full in every session. Above this many words, a rule set
# costs a lot of context: merge rules, or end the ones that no longer apply.
RULE_WORD_CAP = 500


def rule_words(memory: Memory) -> tuple[int, int]:
    """Return (count, words) of the active rules."""
    moment, is_merged = now(), merged_checker(memory.project.root)
    count = words = 0
    for state in memory.states.values():
        if state.get("kind") != "rule":
            continue
        if effective_status(state, moment, is_merged)[0] == "active":
            count += 1
            words += len(str(state.get("text", "")).split())
    return count, words


def preset_note(project: Project, memdir) -> str:
    """One line when a preset in use has rules that the memory lacks. It adds nothing."""
    try:
        used, missing = presets.available(project, memdir)
    except Exception:
        return ""
    if not missing:
        return ""
    names = ", ".join(item.rule.key for item in missing)
    return f"note: new preset rules available: {names}; run `memory preset add {' '.join(used)}`"


def print_advisory(memory: Memory) -> None:
    lines = advisory_rules(memory)
    print(f"{len(lines)} advisory rule(s): no check fails when one is broken.")
    for line in lines:
        print(line)
    if lines:
        print("To enforce one: add a check, then `memory change ID --enforced-by TYPE:VALUE`.")


def run_check(
    project: Project,
    flag: str | None,
    strict: bool = False,
    advisory: bool = False,
    hint: bool = True,
) -> int:
    memdir, source = resolve_memory_dir(project, flag)
    for linked in ensure_all_linked(project, flag):
        print(linked)
    link_exists = any((c / LINK_NAME).is_symlink() for c in project.checkouts)
    if not memdir.is_dir() and not link_exists:
        print(f"memory check: skipped: no memory folder at {memdir}")
        return 0
    errors = check_links(project, memdir)
    warnings: list[str] = []
    if (memdir / "facts").is_dir():
        memory = Memory.open(project, flag)
        record_errors, warnings = check_records(memory)
        errors += record_errors
        warnings += duplicate_rules(memory)
        count, words = rule_words(memory)
        if words > RULE_WORD_CAP:
            print(
                f"note: {count} active rule(s) hold {words} words; every session loads them "
                f"all. Above {RULE_WORD_CAP} words, merge rules or end the ones that do not apply."
            )
        if advisory:
            print_advisory(memory)
        note = preset_note(project, memdir)
        if note:
            print(note)
        line = skills.session_line(memory.dir) if hint else None
        if line:
            print(f"note: {line}")
    else:
        errors.append(f"{memdir}: no facts/ folder; run `memory init`")
    if strict:
        errors += warnings
        warnings = []
    for line in warnings:
        print(f"warning: {line}")
    for line in errors:
        print(f"error: {line}")
    if errors:
        print(f"memory check: {len(errors)} error(s) in {memdir} (from {source})")
        return 1
    print(f"memory check: ok ({len(fact_files(memdir))} fact file(s) in {memdir})")
    return 0
