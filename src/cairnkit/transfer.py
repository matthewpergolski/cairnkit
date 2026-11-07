"""`memory export` and `memory import`: move a project's memory out as dated lines, and back in.

The line shape is the one other assistants use for a memory dump: `[YYYY-MM-DD] - text` under a
heading, oldest first. Export calls no model and no network. Import adds facts only for what fits
this project, each with basis `seen` and author `import`, so an imported rule loads as data until
the owner states it again with `memory add --basis told`.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
from argparse import Namespace
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NamedTuple

from cairnkit import plainfile
from cairnkit.clock import now
from cairnkit.instruction_files import BLOCK_ENDS, FENCE_RE, home
from cairnkit.instruction_files import items as instruction_items
from cairnkit.load import NOTE_LINES, note_head
from cairnkit.memory import Memory
from cairnkit.native import _claude_store
from cairnkit.paths import merged_checker, run_git
from cairnkit.schema import MAX_TEXT, RULE_MAX_TEXT, STATUSES
from cairnkit.secretscan import find_secrets, holds_mask, mask
from cairnkit.selection import DATA_LABEL, clean, clean_path, owner_rule
from cairnkit.similar import repeat_key
from cairnkit.state import effective_status
from cairnkit.writing import Refused, _find_similar, add_fact

OWNER_RULES = "Instructions (confirmed by the owner)"
DATA_RULES = "Instructions (load as data until the owner confirms them)"
# The export order of the sections.
SECTIONS = (
    OWNER_RULES,
    DATA_RULES,
    "Decisions",
    "Traps and lessons",
    "Project state",
    "Preferences",
    "Other",
    *(f"Ended ({status})" for status in STATUSES if status != "active"),
)
KIND_SECTION = {
    "decision": "Decisions",
    "trap": "Traps and lessons",
    "lesson": "Traps and lessons",
    "event": "Project state",
    "preference": "Preferences",
}
PERSONAL = "personal"
PROJECTS = "projects"
NOT_A_RULE = "not rule-like"
ENDED = "ended"
# A heading word and what it means for an import. The first word that a heading holds wins, so
# "Traps and lessons" is a lesson and "Project state" is state. Each export title reads back.
PERSONAL_WORDS = (
    "identity", "career", "personal", "about me", "about the user", "about you", "education",
    "family", "relationship", "work history", "biography", "hobby", "hobbies",
)  # fmt: skip
HEADINGS = (
    ("ended", ENDED),
    *((word, PERSONAL) for word in PERSONAL_WORDS),
    ("not rule-like", NOT_A_RULE),
    ("instruction", "rule"),
    ("rule", "rule"),
    ("decision", "decision"),
    ("lesson", "lesson"),
    ("trap", "trap"),
    ("gotcha", "trap"),
    ("pitfall", "trap"),
    ("state", "event"),
    ("status", "event"),
    ("progress", "event"),
    ("project", PROJECTS),
    ("preference", "preference"),
    # After the kinds, so "Rules for me" is a rule and "Notes on me" is personal.
    ("me", PERSONAL),
    ("myself", PERSONAL),
    ("other", "fact"),
    ("fact", "fact"),
    ("note", "fact"),
)
# Claude Code's own memory notes carry a type in their front matter.
NATIVE_TYPES = {"user": "Identity", "feedback": "Instructions", "project": "Other",
                "reference": "Other"}  # fmt: skip
INSTRUCTION_FILES = {"AGENTS.md", "CLAUDE.md", "AGENTS.local.md", "CLAUDE.local.md"}
MAX_BYTES = 1024 * 1024
SHOWN = 120

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$|^\*\*([^*]+)\*\*:?$")
# A plain line that ends with a colon is a heading too, such as `Personal details, preferences:`.
_COLON_HEADING = re.compile(r"^([^\s\[].{0,58}?):$")
# The section of a line that is no list item and no dated line. The plan lists each such line.
PROSE = ""
# A fence can sit under a list item, so any indent opens one. A closer may sit at most 3 columns
# right of its opener; one further in is text in the block.
_FENCE = re.compile(r"^(?P<indent>[ \t]*)(?P<mark>`{3,}|~{3,})(?P<rest>.*)$")
CLOSER_SLACK = 3
_INFO = re.compile(r"[\w+#.-]*")
# A code block with no language, or one of these, holds text, such as the answer to the prompt.
PLAIN_BLOCKS = ("", "text", "txt", "markdown", "md", "plain", "plaintext")
_WORD = re.compile(r"\w")
_BULLET = re.compile(r"^\s*(?:[-*+\N{BULLET}]|\d+[.)])\s+(.*)$")
_DATED = re.compile(r"^\[([^\]]{0,20})\]\s*(?:[-\N{EN DASH}\N{EM DASH}:]\s*)?(.*)$")
_DAY = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T][\d:.]+Z?)?")
_NO_DATE = re.compile(r"(?i)unknown|undated|no date|n/?a|\?*|yyyy-mm-dd|-*")
_RULE_LIKE = re.compile(
    r"(?i)^(?:always|never|do not|don't|use|prefer|avoid|must|only|keep|run|write|make|put)\b"
    r"|\b(?:must|never|always|do not|don't)\b"
)
_FRONT = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)
_LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
# The end of an exported line that holds the fact's files. A path holds no comma.
_FILES_END = re.compile(r"\s\(files: ([^,]+(?:, [^,]+)*)\)$")


def _with_files(text: str, files: object) -> str:
    if not isinstance(files, list) or not files:
        return text
    return f"{text} (files: {', '.join(map(str, files))})"


def _split_files(text: str) -> tuple[str, tuple[str, ...]]:
    match = _FILES_END.search(text)
    if not match:
        return text, ()
    return text[: match.start()].rstrip(), tuple(match[1].split(", "))


@dataclass(frozen=True)
class Entry:
    """One line of an export or an import: `[date] - text` under a section heading."""

    section: str
    text: str
    date: str | None = None  # YYYY-MM-DD; None when the source gives none
    files: tuple[str, ...] = ()  # repo paths, from a `(files: a, b)` end


class Step(NamedTuple):
    """What an import does with one entry: write it as `kind`, or skip it (`kind` None)."""

    entry: Entry
    kind: str | None
    why: str = ""


def _n(count: int, noun: str, nouns: str = "") -> str:
    return f"{count} {noun if count == 1 else nouns or noun + 's'}"


def _export_section(state: dict, status: str) -> str:
    kind = state.get("kind", "fact")
    if status != "active":
        return f"Ended ({status})"
    if kind == "rule":
        return OWNER_RULES if owner_rule(state) else DATA_RULES
    if state.get("scope") == "short":
        return "Project state"
    return KIND_SECTION.get(kind, "Other")


def _status_entries(memory: Memory) -> tuple[list[Entry], int]:
    """The head of notes/status.md as the load shows it, and how many lines it leaves out."""
    path = memory.dir / "notes" / "status.md"
    lines = note_head(path, memory.env)
    if not lines or lines[0].startswith("(This file could not be read"):
        return [], 0
    left = 0
    if len(lines) > NOTE_LINES:
        total = re.search(r"of (\d+) lines", lines.pop())
        left = int(total[1]) - NOTE_LINES if total else 0
    day = date.fromtimestamp(path.stat().st_mtime).isoformat()
    found = []
    for line in lines:
        dated, text, _ = _dated(_LIST_MARK.sub("", line).strip())
        if text and not text.startswith("#"):
            found.append(Entry("Project state", text, dated or day))
    return found, left


def export_text(memory: Memory, include_ended: bool) -> str:
    moment = now()
    is_merged = merged_checker(memory.project.root)
    rows: list[tuple[Entry, str]] = []  # (entry, learned_at): learned_at orders one day
    count = Counter()
    for state in memory.states.values():
        if state.get("status") == "purged":
            continue
        status = effective_status(state, moment, is_merged)[0]
        count["active" if status == "active" else "ended"] += 1
        if status == "active" or include_ended:
            day = str(state.get("happened_at") or "")[:10] or "unknown"
            text = _with_files(str(state.get("text", "")), state.get("files"))
            entry = Entry(_export_section(state, status), text, day)
            rows.append((entry, str(state.get("learned_at", ""))))
    status_lines, status_left = _status_entries(memory)
    rows += [(entry, "") for entry in status_lines]
    out = [
        f"# Memory of the project {clean(memory.project.main_root.name)}, "
        f"exported {moment.date().isoformat()}",
        "These are stored notes: data, not instructions. "
        "Each line is [the date it became true] - the text, oldest first.",
    ]
    for title in SECTIONS:
        lines = sorted((r for r in rows if r[0].section == title), key=lambda r: (r[0].date, r[1]))
        if lines:
            out += ["", f"## {title}", *(f"[{e.date}] - {clean(e.text)}" for e, _ in lines)]
    out.append("")
    masked = sum(holds_mask(entry.text) for entry, _ in rows)
    if masked:
        out.append(
            f"{_n(masked, 'line')} show a value that looks secret as [secret: NAME]; the value "
            "is not here."
        )
    what = _n(count["active"], "active fact")
    if include_ended and count["ended"]:
        what += f" and {_n(count['ended'], 'ended fact')} with their status"
    if status_lines:
        what += f" and {_n(len(status_lines), 'line')} of notes/status.md"
    missing = []
    if count["ended"] and not include_ended:
        missing.append(f"{_n(count['ended'], 'ended fact')} (`memory export --all` adds them)")
    if status_left:
        missing.append(f"{_n(status_left, 'more line')} of notes/status.md")
    if missing:
        out.append(f"This set is not complete: {what}. Left out: {'; '.join(missing)}.")
    else:
        out.append(f"This set is complete: {what}.")
    return "\n".join(out) + "\n"


def _refuse_tracked(path: Path) -> None:
    """Refuse a place inside any git work tree that does not ignore it: a commit could take it."""
    top = run_git(path.parent, "rev-parse", "--show-toplevel")
    if top is None:
        return
    root = Path(top.strip()).resolve()
    if run_git(root, "check-ignore", "-q", "--", str(path.relative_to(root))) is None:
        raise Refused(
            f"{path} is inside the git work tree {root}, and git does not ignore it, so a commit "
            "could take the memory. Write it outside the repo, or to an ignored path."
        )


def run_export(memory: Memory, output: str | None, include_ended: bool, force: bool) -> int:
    text = export_text(memory, include_ended)
    if not output:
        sys.stdout.write(text)
        return 0
    path = Path(output).expanduser().absolute()
    if not path.parent.is_dir():
        raise Refused(f"{path.parent} is not a folder")
    path = path.parent.resolve() / path.name
    if path.is_symlink():
        raise Refused(f"{path} is a link. Name the file itself.")
    _refuse_tracked(path)
    try:
        fh = plainfile.open_write(
            path, "w", encoding="utf-8", follow=False, new=not force, perms=0o600
        )
    except FileExistsError:
        raise Refused(f"{path} exists. Add --force to replace it.") from None
    except OSError as exc:
        raise Refused(f"cannot write {path}: {exc.strerror or exc}") from None
    with fh:
        os.fchmod(fh.fileno(), 0o600)
        fh.write(text)
    print(f"wrote {clean_path(path)}")
    return 0


def _dated(body: str) -> tuple[str | None, str, bool]:
    """(date, text, had a date mark). `[unknown] - x` has a mark and no date."""
    match = _DATED.match(body)
    if not match:
        return None, body, False
    mark, rest = match[1].strip(), match[2].strip()
    day = _DAY.fullmatch(mark)
    if day:
        with contextlib.suppress(ValueError):
            found = date(int(day[1]), int(day[2]), int(day[3]))
            if found <= now().date():
                return found.isoformat(), rest, True
        return None, rest, True
    if _NO_DATE.fullmatch(mark):
        return None, rest, True
    return None, body, False


class _Block(NamedTuple):
    """An open code block: its fence mark, its language, its first entry and its indent."""

    mark: str
    language: str
    start: int
    indent: int


def _heading(line: str) -> str | None:
    """A `#` line, a bold line or a line that ends with a colon, and no list item."""
    if _BULLET.match(line):
        return None
    marked = _HEADING.match(line) or _COLON_HEADING.match(line)
    return next(g for g in marked.groups() if g).strip() if marked else None


def parse_sections(text: str) -> list[Entry]:
    """Each list item and dated line, under the heading above it.

    Each other line comes back under PROSE, so the plan lists it and the import writes it never.
    Reviews found that each guess at what a plain line means drops lines or stores prose. The
    owner reads the plan and can add a `- ` in front of a line that should go in. So are a line
    in a code block that names a language (`bash`, `yaml`), which is code, a list mark with no
    word after it (`* * *`), and a bold or colon heading with no entry under it, which can be a
    rule written in bold.
    """
    found: list[Entry] = []
    section, heading_line = "Other", None
    blocks: list[_Block] = []
    for raw in text.splitlines():
        line = raw.strip()
        fence = _FENCE.match(raw.rstrip())
        code = [index for index, block in enumerate(blocks) if block.language not in PLAIN_BLOCKS]
        in_code = bool(code)
        if fence:
            mark, rest = fence["mark"], fence["rest"].strip()
            indent = len(fence["indent"].expandtabs(4))
            # In code, a closer of an outer block is code too, so it cannot end the code block.
            closes = [
                index
                for index, block in enumerate(blocks)
                if index >= (code[-1] if code else 0)
                and not rest
                and mark[0] == block.mark[0]
                and len(mark) >= len(block.mark)
                and indent <= block.indent + CLOSER_SLACK
            ]
            if closes:
                del blocks[closes[-1] :]
                continue
            if in_code:
                found.append(Entry(PROSE, line))  # a fence in code is code
            elif mark[0] == "`" and "`" in rest:
                found.append(Entry(PROSE, line))  # a whole fenced line, such as ```text```
            else:
                language = rest.split()[0].lower() if rest else ""
                blocks.append(_Block(mark, language, len(found), indent))
                if not _INFO.fullmatch(rest):
                    found.append(Entry(PROSE, line))
            continue
        if not line:
            continue
        if in_code:
            found.append(Entry(PROSE, line))
            continue
        heading = _heading(line)
        if heading:
            if heading_line:
                found.append(Entry(PROSE, heading_line))
            section, heading_line = heading, (None if line.startswith("#") else line)
            continue
        bullet = _BULLET.match(line)
        day, body, marked = _dated(bullet[1].strip() if bullet else line)
        if body and (bullet or marked) and _WORD.search(body):
            body, files = _split_files(body)
            found.append(Entry(section, body, day, files))
            heading_line = None
        else:
            found.append(Entry(PROSE, line))
    if heading_line:
        found.append(Entry(PROSE, heading_line))
    if blocks:
        # A block that never closes can hold code, so nothing from it on is written.
        start = blocks[0].start
        found[start:] = [
            entry if entry.section == PROSE else Entry(PROSE, entry.text) for entry in found[start:]
        ]
    return found


def parse_instructions(text: str) -> list[Entry]:
    """The list items of an AGENTS.md or CLAUDE.md, outside code and outside memory's block."""
    found = []
    in_code = False
    block_end = None
    for raw in text.splitlines():
        line = raw.strip()
        if block_end or line in BLOCK_ENDS:
            block_end = None if line == block_end else (block_end or BLOCK_ENDS[line])
            continue
        if FENCE_RE.match(raw):
            in_code = not in_code
            continue
        bullet = _BULLET.match(raw)
        if in_code or not bullet:
            continue
        body = bullet[1].strip()
        found.append(Entry("Instructions" if _RULE_LIKE.search(body) else NOT_A_RULE, body))
    return found


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_BYTES:
            raise Refused(f"{path} is larger than {MAX_BYTES // 1024} KB")
        return plainfile.read_text(path, encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise Refused(f"cannot read {path}: {exc.strerror or exc}") from None


def parse_native(text: str) -> list[Entry]:
    """One Claude Code memory note: its type from the front matter, its body as one text."""
    match = _FRONT.match(text)
    if not match:
        return parse_sections(text)
    front, body = match[1], " ".join(match[2].split())
    kind = re.search(r"(?m)^\s*type:\s*[\"']?([\w-]+)", front)
    day = re.search(r"(?m)^\s*modified:\s*[\"']?(\d{4}-\d{2}-\d{2})", front)
    # A type this table does not know is no heading this import maps, so its note is skipped.
    section = NATIVE_TYPES.get(kind[1], f"type {kind[1]}") if kind else "no type"
    return [Entry(section, body, day[1] if day else None)] if body else []


def read_source(memory: Memory, target: str | None, native: bool) -> list[tuple[str, Entry]]:
    """(source name, entry) for each entry. The source name goes into the fact's source."""
    if native:
        target = str(_claude_store(memory.project.main_root))
        if not Path(target).is_dir():
            raise Refused(f"Claude Code keeps no memory notes for this project ({target})")
    if target in (None, "-"):
        text = sys.stdin.read(MAX_BYTES + 1)
        if len(text) > MAX_BYTES:
            raise Refused(f"the paste is larger than {MAX_BYTES // 1024} KB")
        return [("paste", e) for e in parse_sections(text.removeprefix("\ufeff"))]
    path = Path(target).expanduser()
    if path.name == "MEMORY.md":
        notes = [p for p in path.parent.glob("*.md") if p.name != "MEMORY.md"]
        path = path.parent if any(_FRONT.match(_read(p)) for p in notes) else path
    if path.is_dir():
        notes = sorted(p for p in path.glob("*.md") if p.name != "MEMORY.md")
        return [(p.name, e) for p in notes for e in parse_native(_read(p))]
    text = _read(path)
    if path.name in INSTRUCTION_FILES:
        return [(path.name, e) for e in parse_instructions(text)]
    return [(path.name, e) for e in parse_native(text)]


def heading_kind(section: str) -> str | None:
    """What a heading's title means, matched on whole words. `Other: facts about the project`
    has the title `Other`."""
    title = section.split(":", 1)[0].lower()
    return next((kind for word, kind in HEADINGS if _has_words(title, word)), None)


def _has_words(text: str, words: str) -> bool:
    """`words` in `text` as whole words; a plural `s` counts, so `Decisions` holds `decision`."""
    return re.search(rf"(?<![\w-]){re.escape(words)}s?(?![\w-])", text) is not None


def _kind(entry: Entry, project: str) -> tuple[str | None, str]:
    """The kind an entry is written as, or None and why it is skipped."""
    if entry.section == PROSE:
        return None, "no list item and no dated line, so not read (put `- ` in front to add it)"
    kind = heading_kind(entry.section)
    if kind == PROJECTS:
        if _has_words(entry.text.lower(), project):
            return "fact", ""
        return None, f"about another project, not {project}"
    skips = {
        PERSONAL: PERSONAL,
        ENDED: "ended in the source",
        NOT_A_RULE: "not rule-like",
        None: f"under the heading {clean(entry.section)!r}, which this import does not map",
    }
    if kind in skips:
        return None, skips[kind]
    if kind == "rule" and len(entry.text) > RULE_MAX_TEXT:
        return "preference", f"longer than a rule may be ({RULE_MAX_TEXT} characters)"
    return kind, ""


def _args(entry: Entry, kind: str, source: str) -> Namespace:
    return Namespace(
        text=entry.text, kind=kind, area="general", basis="seen", source=source, tag=None,
        happened_at=entry.date, link=None, pinned=False, enforced_by=None, supersedes=None,
        reason=None, short=False, expires=None, until_merged=None, summary=None, author="import",
        files=list(entry.files) or None,
    )  # fmt: skip


def _status_keys(memory: Memory) -> set[str]:
    try:
        text = plainfile.read_text(
            memory.dir / "notes" / "status.md", encoding="utf-8", errors="replace"
        )
    except OSError:
        return set()
    return {repeat_key(_LIST_MARK.sub("", line)) for line in text.splitlines()}


def plan(memory: Memory, entries: list[tuple[str, Entry]]) -> list[Step]:
    """Each entry's step. The same text as any fact, active or ended, is never written again."""
    moment = now()
    is_merged = merged_checker(memory.project.root)
    known = {
        repeat_key(str(s.get("text", ""))): s
        for s in sorted(memory.states.values(), key=lambda s: s.get("learned_at", ""))
        if s.get("status") != "purged"
    }
    in_status = _status_keys(memory)
    in_files = instruction_items(memory.project.root)
    project = memory.project.main_root.name.lower()
    seen: set[str] = set()
    steps = []
    for _, entry in entries:
        kind, why = _kind(entry, project)
        key = repeat_key(entry.text)
        secrets = find_secrets(entry.text, memory.env)
        old = known.get(key)
        held = kind == "rule" and home(in_files, entry.text)
        if not kind:
            pass
        elif secrets:
            why = f"looks like a secret ({', '.join(secrets)})"
        elif holds_mask(entry.text):
            why = "holds a masked secret; write the true text without the value"
        elif len(entry.text) > MAX_TEXT:
            why = f"longer than {MAX_TEXT} characters"
        elif old:
            why = f"already in this memory as {old['id']} ({old.get('status', 'active')})"
        elif key in seen:
            why = "the same text as a line above"
        elif key in in_status:
            why = "already in notes/status.md"
        elif held:
            why = f"already in {held.file} here"
        else:
            seen.add(key)
            near = _find_similar(memory, _args(entry, kind, ""), moment, is_merged)
            note = f"near {near[0]['id']}, linked similar_to" if near else why
            steps.append(Step(entry, kind, note))
            continue
        steps.append(Step(entry, None, why))
    return steps


def _shown(memory: Memory, text: str) -> str:
    line = clean(mask(text, memory.env))
    return line if len(line) <= SHOWN else line[: SHOWN - 3] + "..."


def _add_line(memory: Memory, step: Step, fact_id: str | None) -> str:
    parts = [step.kind or ""]
    if step.kind == "rule":
        parts.append("loads as data")
    parts.append(step.entry.date or "no date, so today")
    if step.why:
        parts.append(step.why)
    head = f"{fact_id} " if fact_id else ""
    return f"  + {head}{', '.join(parts)}: {_shown(memory, step.entry.text)}"


def _source(name: str, today: str) -> str:
    return f"import:{'-'.join(name.split())}:{today}"


def run_import(memory: Memory, target: str | None, native: bool, yes: bool) -> int:
    entries = read_source(memory, target, native)
    steps = plan(memory, entries)
    today = now().date().isoformat()
    sources = {id(entry): _source(name, today) for name, entry in entries}
    adds = [s for s in steps if s.kind]
    skips = [s for s in steps if not s.kind]
    if native:
        name = "Claude Code's notes for this project"
    else:
        name = "paste" if target in (None, "-") else Path(target).name
    read = sum(entry.section != PROSE for _, entry in entries)
    print(f"memory import: {clean(name)}, {_n(read, 'entry', 'entries')} read.")
    print(
        f"{'Added' if yes else 'Would add'} {len(adds)} (basis seen, author import; {DATA_LABEL}):"
    )
    rules = 0
    for step in adds:
        fact_id = None
        if yes:
            args = _args(step.entry, step.kind, sources[id(step.entry)])
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    fact_id = add_fact(memory, args)
            except Refused as exc:
                print(f"  ! not written ({exc}): {_shown(memory, step.entry.text)}")
                continue
            rules += step.kind == "rule"
        print(_add_line(memory, step, fact_id))
    print(f"{'Skipped' if yes else 'Would skip'} {len(skips)}:")
    personal = Counter(s.entry.section for s in skips if s.why == PERSONAL)
    if personal:
        counts = ", ".join(f"{clean(section)} {n}" for section, n in sorted(personal.items()))
        print(
            f"  - {sum(personal.values())} personal entries ({counts}): this memory keeps only "
            "what fits the project."
        )
    for step in skips:
        if step.why != PERSONAL:
            print(f"  - {step.why}: {_shown(memory, step.entry.text)}")
    if not yes:
        then = f" Run again with --yes to write {_n(len(adds), 'fact')}." if adds else ""
        print(f"This changed nothing.{then}")
    elif rules:
        print(
            f"{_n(rules, 'rule')} load as data. If you stated one, lift it: "
            'memory add "TEXT" --kind rule --basis told'
        )
    return 0


def prompt_text(project: str) -> str:
    return f"""I keep a private memory for one software project, "{project}". Tell me what you \
know about this project from our past chats and your saved memory. Leave out other projects, and \
leave out facts about me as a person.

Sort it under these headings, and leave out a heading with nothing under it:
## Instructions: rules I gave you for work on this project
## Decisions: choices made for the project, and why
## Traps and lessons: mistakes, surprises, what failed and what worked
## Project state: where the work stands now
## Preferences: how I like the work done
## Other: other facts about the project

Write each item on its own line as [YYYY-MM-DD] - text, oldest first. Use the date it became \
true, or [unknown]. Keep my own words where you can. Add no advice and no summary.

Put the whole list in one code block. After the code block, write one line that says if this is \
everything you know about the project, or what you left out.
"""
