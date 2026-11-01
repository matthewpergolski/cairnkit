"""`memory check`: report every problem in the memory and its links."""

from __future__ import annotations

import glob
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from cairnkit import (
    deadline,
    enforcement,
    githook,
    instruction_files,
    migrate_refs,
    native,
    presets,
    refresh,
)
from cairnkit.clock import now
from cairnkit.config import config_problems, secrets_in_config
from cairnkit.docs_cmd import status_line
from cairnkit.ignore import keep_out_of_git
from cairnkit.init import ensure_all_linked
from cairnkit.memory import Memory, MemoryMissing
from cairnkit.migrate_refs import OLD_SUFFIX
from cairnkit.paths import (
    ENV_DIR,
    LINK_NAME,
    PATH_FILE,
    Project,
    lost_memory,
    lost_note,
    merged_checker,
    owner_line,
    resolve_memory_dir,
    run_git,
)
from cairnkit.reading import note_files
from cairnkit.schema import validate_record
from cairnkit.secretscan import find_in_record, find_secrets, mask, real_secrets
from cairnkit.selection import RULE_WORD_LIMIT, clean
from cairnkit.state import effective_status
from cairnkit.store import Located, fact_files, read_located, repaired_lines


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


REPAIR = "; run `memory repair`"
MAX_OLD_FILES = 500
MAX_OLD_BYTES = 256 * 1024


@dataclass
class RecordIndex:
    """What a check of one record needs to know about the others."""

    fact_ids: Counter
    known: set
    kinds: dict

    @classmethod
    def of(cls, located: list[Located]) -> RecordIndex:
        facts = [i.record for i in located if i.record.get("type") == "fact"]
        tombstones = {i.record.get("id") for i in located if i.record.get("type") == "tombstone"}
        ids = Counter(f.get("id") for f in facts)
        return cls(ids, set(ids) | tombstones, {f.get("id"): f.get("kind") for f in facts})


def record_problems(item: Located, index: RecordIndex) -> list[str]:
    """What is wrong with one record, apart from a secret. `memory repair` can settle these."""
    rec = item.record
    problems = list(validate_record(rec))
    kind = rec.get("type")
    if kind == "fact" and index.fact_ids[rec.get("id")] > 1:
        problems.append(f"duplicate id {rec.get('id')}")
    if kind == "change" and rec.get("id") not in index.known:
        problems.append(f"change names an unknown fact {rec.get('id')}")
    target = rec.get("superseded_by")
    if target and target not in index.known:
        problems.append(f"superseded_by {target} is not a known fact")
    for link in (rec.get("links") or []) + (rec.get("add_links") or []):
        if isinstance(link, dict) and link.get("id") not in index.known:
            problems.append(f"link to unknown fact {link.get('id')}")
    if kind == "change" and rec.get("enforced_by") and index.kinds.get(rec.get("id")) != "rule":
        problems.append("enforced_by is only for kind 'rule'")
    return problems


def writer_differs(item: Located) -> str | None:
    writer = item.record.get("writer")
    if writer and writer != item.path.stem and item.record.get("type") != "tombstone":
        return f"writer {writer!r} differs from the file name"
    return None


def check_records(memory: Memory) -> tuple[list[str], list[str]]:
    located, bad = read_located(fact_files(memory.dir))
    errors = [line if ": cannot read: " in line else line + REPAIR for line in bad]
    config_errors, warnings = config_problems(memory.dir)
    errors += [line + REPAIR for line in config_errors]
    errors += [line + REPAIR for line in secrets_in_config(memory.dir, memory.env)]
    warnings = [line + REPAIR for line in warnings]
    done = repaired_lines(memory.dir, located)
    index = RecordIndex.of(located)
    for item in located:
        rec, where = item.record, f"{item.path.name}:{item.line}"
        settled = (item.path.name, item.sha) in done
        problems = [] if settled else [p + REPAIR for p in record_problems(item, index)]
        rec_id = rec.get("id")
        found = find_in_record(rec, memory.env)
        # A fact has its own line below, once. These records reach no reader or state.
        if found and rec_id and rec_id not in memory.masked and not find_secrets(rec_id):
            problems.append(
                f"{rec_id} looks like a secret ({', '.join(found)}). It stays on disk until "
                f"purged. Run `memory purge {rec_id} --reason secret --yes`."
            )
        differs = writer_differs(item)
        if differs and not settled:
            warnings.append(f"{where}: {differs}{REPAIR}")
        errors += [f"{where}: {problem}" for problem in problems]
    errors += [
        memory.secret_problem(fact_id)
        for fact_id in sorted(memory.masked)
        if not memory.only_plain(fact_id)
    ]
    errors += [memory.secret_line_problem(line) for line in memory.secret_lines]
    root = memory.project.root
    for state in sorted(memory.states.values(), key=lambda s: s["id"]):
        held = state.get("held_by")
        if state.get("status") == "promoted" and held and not _path_known(root, held):
            errors.append(
                f"{state['id']}: held_by {held} does not exist; run "
                f'`memory change {state["id"]} --status active --reason "..."` to load the '
                f"fact again, or `memory change {state['id']} --status promoted --held-by "
                f'PATH --reason "..."` to name the file that holds it now'
            )
    # A problem can quote a stored value: `kind 'ghp_...' is not one of ...`.
    return [mask(line, memory.env) for line in errors], [
        mask(line, memory.env) for line in warnings
    ]


def _path_known(root, path: str) -> bool:
    """True when the path exists here, or in the history of any branch."""
    if (root / path).exists():
        return True
    found = run_git(root, "log", "--all", "-1", "--format=%h", "--", path, timeout=2.0)
    return found is None or bool(found)  # git cannot say: a slow git is not a problem to report


def _old_copy_files(project: Project) -> list[Path]:
    """The files that a migration moved aside. Each one is text that no read can mask."""
    root = project.main_root
    found: list[Path] = []
    for folder in sorted(root.parent.glob(f"{glob.escape(root.name)}{OLD_SUFFIX}*")):
        for dirpath, _, names in os.walk(folder):
            found += [Path(dirpath) / name for name in sorted(names)]
    return found[:MAX_OLD_FILES]


def secrets_in_old_copy(memory: Memory) -> list[str]:
    root = memory.project.main_root
    warnings = []
    for path in _old_copy_files(memory.project):
        try:
            if path.stat().st_size > MAX_OLD_BYTES:
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, start=1):
            found = real_secrets(line, memory.env)
            if found:
                warnings.append(
                    f"{path.relative_to(root.parent)}:{number}: looks like a secret "
                    f"({', '.join(found)}). A migration moved this copy aside, and it stays on "
                    "disk. Remove that line, or the file if nothing in it is needed."
                )
    return warnings


def history_note(memory: Memory) -> str | None:
    """Git history can hold what was committed. The tool cannot mask it and does not rewrite it."""
    root = memory.project.root
    log = run_git(root, "log", "--all", "-p", "--format=commit %h", "--", LINK_NAME, timeout=2.0)
    commit = None
    for line in (log or "").splitlines():
        if line.startswith("commit "):
            commit = line.split()[1]
        elif line.startswith("+") and not line.startswith("+++"):
            found = real_secrets(line[1:], memory.env)
            if found:
                return (
                    f"note: git history still holds a value that looks secret in {LINK_NAME}/ "
                    f"(commit {commit}: {', '.join(found)}). This tool does not rewrite history. "
                    "If the value is real, change it where it is used."
                )
    return None


def secrets_in_notes(memory: Memory) -> list[str]:
    """Warnings for note lines that hold a secret. Notes are not checked at write time."""
    warnings = secrets_in_old_copy(memory)
    proposals = sorted((memory.dir / "proposals").glob("*.*"))
    files = [*note_files(memory.dir / "notes"), *note_files(memory.dir / "branches"), *proposals]
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        rel = path.relative_to(memory.dir).as_posix()
        for number, line in enumerate(lines, start=1):
            found = find_secrets(line, memory.env)
            if found:
                warnings.append(
                    f"{rel}:{number}: looks like a secret ({', '.join(found)}); remove that line"
                )
    return warnings


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


def false_enforcement(memory: Memory, state: githook.HookState) -> list[str]:
    """Warnings for active rules that name a check that is not there."""
    moment, is_merged = now(), merged_checker(memory.project.root)
    # The hidden-hook warning already explains a git hook that does not run, and it must not
    # fail --strict.
    hidden = state.dead or state.line.startswith("warning:")
    return [
        f"rule {state['id']}: enforced_by {state['enforced_by']}: no such check here. Add the "
        f"check, or run `memory change {state['id']} --no-enforced-by --reason WHY`"
        for state in sorted(memory.states.values(), key=lambda s: s.get("learned_at", ""))
        if state.get("kind") == "rule"
        and effective_status(state, moment, is_merged)[0] == "active"
        and enforcement.is_false(memory.project, state)
        and not (hidden and state["enforced_by"].startswith("githook:"))
    ]


def advisory_rules(memory: Memory) -> list[str]:
    """Active rules that no check enforces: they are prose only."""
    moment, is_merged = now(), merged_checker(memory.project.root)
    lines = []
    for state in sorted(memory.states.values(), key=lambda s: s.get("learned_at", "")):
        if state.get("kind") != "rule":
            continue
        if state.get("enforced_by") and not enforcement.is_false(memory.project, state):
            continue
        if effective_status(state, moment, is_merged)[0] == "active":
            lines.append(clean(f"- [{state['id']}] {state.get('text', '')}"))
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


def _bad_path_file(project: Project) -> list[str]:
    """A path file that is not text is ignored, so the memory can be a different one."""
    try:
        (project.home / PATH_FILE).read_text()
    except OSError:
        return []
    except UnicodeDecodeError:
        return [f"{PATH_FILE} is not text, so it is ignored. Fix it: memory init --path FOLDER"]
    return []


@dataclass
class Health:
    """The one answer about a memory. Status, check, load and stop read it.

    `errors` fail `memory check`. `warnings` fail `--strict`. `todo` is work outside the facts. It
    fails no check, because it must not stop a commit, and an `ok` beside it would be false.
    """

    memdir: Path | None = None
    source: str = ""
    memory: Memory | None = None
    missing: str | None = None
    gone: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)

    def answer(self, strict: bool = False) -> str:
        if self.missing:
            return f"memory: not loaded: {self.missing}"
        errors = len(self.errors) + (len(self.warnings) if strict else 0)
        warnings = 0 if strict else len(self.warnings)
        counts = [
            f"{count} {label}"
            for count, label in (
                (errors, "error(s)"),
                (warnings, "warning(s)"),
                (len(self.todo), "to do"),
            )
            if count
        ]
        if counts:
            return f"memory check: {', '.join(counts)} in {self.memdir} (from {self.source})"
        return f"memory check: ok ({len(fact_files(self.memdir))} fact file(s) in {self.memdir})"

    @property
    def is_ok(self) -> bool:
        return not (self.missing or self.errors or self.warnings or self.todo)

    def details(self, strict: bool = False) -> list[str]:
        return [
            *(f"warning: {line}" for line in ([] if strict else self.warnings)),
            *(f"error: {line}" for line in (self.warnings if strict else []) + self.errors),
        ]

    def exit_code(self, strict: bool = False) -> int:
        if self.missing:
            return 1 if self.gone else 0
        return 1 if self.errors or (strict and self.warnings) else 0


def _hook_lines(state: githook.HookState, health: Health) -> None:
    if state.dead:
        health.errors.append(state.line)
    elif state.line.startswith("git hooks: on"):
        health.info.append(state.line)
    elif state.line:
        health.todo.append(state.line)


def _read_health(project: Project, flag: str | None) -> Health:
    memdir, source = resolve_memory_dir(project, flag)
    health = Health(memdir, source, linked=ensure_all_linked(project, flag))
    health.warnings += _bad_path_file(project)
    has_facts = (memdir / "facts").is_dir()
    if not has_facts and source not in ("flag", ENV_DIR):
        lost = lost_memory(project)
        if lost:
            health.missing, health.gone = lost_note(lost), bool(lost.gone)
            return health
    if not memdir.is_dir() and not any((c / LINK_NAME).is_symlink() for c in project.checkouts):
        health.missing = f"no memory folder at {memdir} (from {source}); run `memory init`"
        return health
    health.errors += check_links(project, memdir)
    if not has_facts:
        health.errors.append(f"{memdir}: no facts/ folder; run `memory init`")
        return health
    health.errors += keep_out_of_git(memdir)
    memory = health.memory = Memory.open(project, flag)
    record_errors, warnings = check_records(memory)
    health.errors += record_errors
    hooks = githook.hook_state(project)
    health.warnings += warnings + duplicate_rules(memory) + false_enforcement(memory, hooks)
    health.warnings += secrets_in_notes(memory)
    # The load tells the agent that a plain word can stay, so --strict must not fail on it.
    health.info += [
        f"note: {memory.secret_problem(fact_id)}"
        for fact_id in sorted(memory.masked)
        if memory.only_plain(fact_id)
    ]
    health.info += list(filter(None, (history_note(memory), native.secret_note(memory))))
    owner = owner_line(project, memdir)
    if owner:
        health.info.append(owner)
    count, words = rule_words(memory)
    if words > RULE_WORD_CAP:
        health.todo.append(
            f"note: {count} active rule(s) hold {words} words; every session loads up to "
            f"{RULE_WORD_LIMIT} words of them. Above {RULE_WORD_CAP} words, merge rules or end "
            "the ones that do not apply."
        )
    health.todo += migrate_refs.check_notes(memdir)
    _hook_lines(hooks, health)
    # For a hook that it can fix, repo_line says only what the hook state already said.
    repo = refresh.gone_python_line(project) if hooks.fixable else refresh.repo_line(project, flag)
    docs = status_line(project) if deadline.has_time() else None
    health.todo += [line for line in (repo, docs) if line]
    note = preset_note(project, memdir)
    if note:
        health.info.append(note)
    return health


def read_health(project: Project, flag: str | None = None) -> Health:
    """Compute the answer once. A command never fails on the way to saying what is wrong."""
    try:
        return _read_health(project, flag)
    except MemoryMissing as exc:
        return Health(missing=str(exc))
    except Exception as exc:
        return Health(missing=f"unexpected error: {exc}", gone=True)


def run_check(
    project: Project,
    flag: str | None,
    strict: bool = False,
    advisory: bool = False,
) -> int:
    health = read_health(project, flag)
    for line in health.linked:
        print(line)
    if advisory and health.memory:
        print_advisory(health.memory)
    for line in health.details(strict):
        print(line)
    print(health.answer(strict))
    for line in health.todo + health.info:
        print(line)
    return health.exit_code(strict)
