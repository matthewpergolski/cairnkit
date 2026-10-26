"""Rule presets: named sets of rule facts, kept as TOML data in `preset_data/`.

`memory init --preset NAME` and `memory preset add NAME` add the rules of a preset
that the memory does not hold yet. A rule is never added again after a person
ended it, and never when a rule with the same text is already there.
`memory preset add --file PATH` does the same for a preset file that the project
owns, in the same format.
"""

from __future__ import annotations

import contextlib
import re
import secrets
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from cairnkit.clock import now, stamp
from cairnkit.state import fold
from cairnkit.store import append_records, fact_files, read_records

DATA = Path(__file__).parent / "preset_data"
DEFAULT = "commits"  # its rules keep `source: default`
NONE = "none"
WRITER = "default"
FILE_FIELDS = {"summary", "includes", "include_rules", "rule"}
RULE_FIELDS = {"key", "text", "area", "tags", "when", "enforced_by", "enforce_when"}
KEY = re.compile(r"([a-z][a-z0-9-]*)\.[a-z0-9][a-z0-9-]*")


class UnknownPreset(ValueError):
    pass


class BadPresetFile(UnknownPreset):
    pass


@dataclass(frozen=True)
class Rule:
    key: str
    text: str
    area: str
    tags: tuple[str, ...]
    origin: str
    when: str | None = None
    enforced_by: str | None = None
    enforce_when: str | None = None

    @property
    def source(self) -> str:
        return "default" if self.origin == DEFAULT else f"preset:{self.origin}"


@dataclass
class Preset:
    name: str
    summary: str
    includes: list[str] = field(default_factory=list)
    include_rules: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)


def names() -> list[str]:
    return sorted(p.stem for p in DATA.glob("*.toml"))


def load_preset(name: str) -> Preset:
    path = DATA / f"{name}.toml"
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name) or not path.is_file():
        known = ", ".join([*names(), NONE])
        raise UnknownPreset(f"unknown preset {name!r}; known presets: {known}")
    return _preset(name, tomllib.loads(path.read_text(encoding="utf-8")))


def _preset(name: str, data: dict) -> Preset:
    rules = [
        Rule(
            r["key"],
            r["text"],
            r["area"],
            tuple(r.get("tags", [])),
            name,
            r.get("when"),
            r.get("enforced_by"),
            r.get("enforce_when"),
        )
        for r in data.get("rule", [])
    ]
    return Preset(
        name,
        data.get("summary", ""),
        data.get("includes", []),
        data.get("include_rules", []),
        rules,
    )


def load_file(path: str) -> Preset:
    """A preset file that the project owns. Raise BadPresetFile when it is not valid.

    All its keys share one prefix, which is not the name of a built-in preset.
    That prefix is the preset name, so its rules get `source: preset:<prefix>`.
    """
    from cairnkit.detect import NAMES
    from cairnkit.schema import validate_record
    from cairnkit.secretscan import find_secrets

    def bad(why: str) -> BadPresetFile:
        return BadPresetFile(f"preset file {path}: {why}")

    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise bad(f"cannot read it ({exc.strerror or exc})") from exc
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise bad(f"not valid TOML ({exc})") from exc
    extra = sorted(set(data) - FILE_FIELDS)
    if extra:
        raise bad(f"unknown field {extra[0]!r}")
    for field_name in ("includes", "include_rules"):
        value = data.get(field_name, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise bad(f"{field_name} must be a list of strings")
    rules = data.get("rule")
    if not isinstance(rules, list) or not rules:
        raise bad("it has no [[rule]] table")
    prefixes, seen = set(), set()
    for n, rule in enumerate(rules, 1):
        if not isinstance(rule, dict):
            raise bad(f"rule {n} is not a table")
        where = f"rule {rule['key']}" if isinstance(rule.get("key"), str) else f"rule {n}"
        extra = sorted(set(rule) - RULE_FIELDS)
        if extra:
            raise bad(f"{where}: unknown field {extra[0]!r}")
        for field_name in ("key", "text", "area"):
            if not isinstance(rule.get(field_name), str) or not rule[field_name].strip():
                raise bad(f"{where} needs {field_name}")
        for field_name in ("when", "enforced_by", "enforce_when"):
            if not isinstance(rule.get(field_name, ""), str):
                raise bad(f"{where}: {field_name} must be a string")
        match = KEY.fullmatch(rule["key"])
        if not match:
            raise bad(f"key {rule['key']!r} is not <prefix>.<name> in lower case")
        if rule["key"] in seen:
            raise bad(f"key {rule['key']} is used twice")
        seen.add(rule["key"])
        prefixes.add(match[1])
        tags = rule.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise bad(f"{where}: tags must be a list of strings")
        for field_name in ("when", "enforce_when"):
            if rule.get(field_name) not in (None, *NAMES):
                raise bad(f"{where}: unknown detection name {rule[field_name]!r}")
        if rule.get("enforced_by") and not rule.get("enforce_when"):
            raise bad(f"{where}: enforced_by needs enforce_when")
        if find_secrets(rule["text"]):
            raise bad(f"{where}: the text looks like a secret")
    if len(prefixes) > 1:
        raise bad(f"the keys use more than one prefix ({', '.join(sorted(prefixes))})")
    name = prefixes.pop()
    if name in [*names(), NONE]:
        raise bad(f"the key prefix {name!r} is the name of a built-in preset; use another")
    preset = _preset(name, data)
    for rule in preset.rules:  # the fact that write() would make, with the schema checks
        errors = validate_record(_record(rule, "f-00000000-0000", now(), rule.enforced_by))
        if errors:
            raise bad(f"rule {rule.key}: {errors[0]}")
    try:
        resolve([], [preset])
    except UnknownPreset as exc:
        raise bad(str(exc)) from exc
    return preset


def check_names(wanted: list[str]) -> None:
    """Raise UnknownPreset for a bad name or list."""
    if NONE in wanted and len(set(wanted)) > 1:
        raise UnknownPreset(f"preset {NONE!r} cannot be used with other presets")
    for name in wanted:
        if name != NONE:
            load_preset(name)


def resolve(wanted: list[str], files: Sequence[Preset] = ()) -> list[Rule]:
    """The rules of the presets and preset files, with their includes, in order, each key once."""
    out: dict[str, Rule] = {}

    def take(preset: Preset, seen: tuple[str, ...]) -> None:
        for inc in preset.includes:
            visit(inc, seen)
        for key in preset.include_rules:
            origin = key.split(".", 1)[0]
            rule = next((r for r in load_preset(origin).rules if r.key == key), None)
            if rule is None:
                raise UnknownPreset(f"preset {preset.name!r} includes unknown rule {key!r}")
            out.setdefault(key, rule)
        for rule in preset.rules:
            out.setdefault(rule.key, rule)

    def visit(name: str, seen: tuple[str, ...]) -> None:
        if name == NONE or name in seen:
            return
        take(load_preset(name), (*seen, name))

    for name in wanted:
        visit(name, ())
    for preset in files:
        take(preset, ())
    return list(out.values())


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split()).rstrip(".")


@dataclass
class Planned:
    rule: Rule
    add: bool
    note: str
    enforced_by: str | None = None
    detected: bool = True


def _states(memdir: Path | None) -> list[dict]:
    if memdir is None or not (memdir / "facts").is_dir():
        return []
    records, _ = read_records(fact_files(memdir))
    return list(fold(records).values())


def _held(states: list[dict], rule: Rule) -> bool:
    keys = {s["preset_rule"] for s in states if s.get("preset_rule")}
    texts = {_norm(s["text"]) for s in states if s.get("kind") == "rule" and s.get("text")}
    return rule.key in keys or _norm(rule.text) in texts


def used_presets(states: list[dict]) -> list[str]:
    """The presets that the memory was set up with, from the rules it holds.

    A preset counts when the memory holds one of its own rules that a larger
    preset it already counts does not cover. So a `dev` memory is `dev`, not
    also `basic` and `commits`.
    """
    used: list[str] = []
    covered: set[str] = set()
    for name in sorted(names(), key=lambda n: (-len(resolve([n])), n)):
        held = [r for r in load_preset(name).rules if _held(states, r)]
        if held and not all(r.key in covered for r in held):
            used.append(name)
            covered |= {r.key for r in resolve([name])}
    return used


def available(project, memdir: Path) -> tuple[list[str], list[Planned]]:
    """The presets in use, and the rules of them that a `memory preset add` would add now."""
    from cairnkit.detect import detect
    from cairnkit.githook import guard_installed
    from cairnkit.rules import GUARDED

    used = used_presets(_states(memdir))
    if not used:
        return [], []
    guarded = GUARDED if guard_installed(project) else None
    planned = plan(memdir, resolve(used), guarded, detect(project.root))
    return used, [p for p in planned if p.add]


def plan(
    memdir: Path | None,
    rules: list[Rule],
    guarded_text: str | None = None,
    found: dict | None = None,
) -> list[Planned]:
    """Decide, for each rule, whether to add it, and why.

    `found` holds the toolchain findings (see detect.py). A rule with `when` is
    added only when its finding is true. Of two rules with the same text, only
    the first is added, also when both come in now.
    """
    found = found or {}
    states = _states(memdir)
    by_key = {s["preset_rule"]: s for s in states if s.get("preset_rule")}
    # normalized text -> the stored fact id, or the key of a rule planned here
    by_text = {
        _norm(s["text"]): s["id"] for s in states if s.get("kind") == "rule" and s.get("text")
    }
    out = []
    for rule in rules:
        have = by_key.get(rule.key)
        same = by_text.get(_norm(rule.text))
        need = found.get(rule.when) if rule.when else None
        if have and have.get("status") == "active":
            out.append(Planned(rule, False, "already in memory"))
        elif have:
            out.append(Planned(rule, False, f"ended ({have.get('status')}); not added again"))
        elif same:
            out.append(Planned(rule, False, f"same text as rule {same}"))
        elif rule.when and not (need and need.found):
            why = need.reason if need else "no detection"
            out.append(Planned(rule, False, f"not detected ({why})", detected=False))
        else:
            enforced, note = rule_enforcement(rule, guarded_text, found)
            out.append(Planned(rule, True, note, enforced))
            by_text[_norm(rule.text)] = rule.key
    return out


def rule_enforcement(
    rule: Rule, guarded_text: str | None, found: dict | None = None
) -> tuple[str | None, str]:
    """Return (enforced_by or None, the reason)."""
    from cairnkit.githook import GUARD_REF

    found = found or {}
    if guarded_text and rule.text == guarded_text:
        return GUARD_REF, "the commit-msg guard is installed"
    parts = [found[rule.when].reason] if rule.when and rule.when in found else []
    if rule.enforced_by:
        check = found.get(rule.enforce_when)
        if check is not None:
            parts.append(check.reason)
        if check is not None and check.found:
            return rule.enforced_by, "; ".join(parts)
    return None, "; ".join(parts) or "advisory"


def _record(rule: Rule, fid: str, moment, enforced_by: str | None) -> dict:
    rec = {
        "type": "fact",
        "id": fid,
        "kind": "rule",
        "text": rule.text,
        "area": rule.area,
        "tags": list(rule.tags),
        "happened_at": moment.date().isoformat(),
        "learned_at": stamp(moment),
        "source": rule.source,
        "basis": "told",
        "status": "active",
        "scope": "long",
        "writer": WRITER,
        "preset_rule": rule.key,
    }
    if enforced_by:
        rec["enforced_by"] = enforced_by
    return rec


def write(memdir: Path, planned: list[Planned]) -> int:
    moment = now()
    records, used = [], set()
    for item in planned:
        if not item.add:
            continue
        fid = f"f-{moment:%Y%m%d}-{secrets.token_hex(2)}"
        while fid in used:
            fid = f"f-{moment:%Y%m%d}-{secrets.token_hex(2)}"
        used.add(fid)
        records.append(_record(item.rule, fid, moment, item.enforced_by))
    if records:
        append_records(memdir / "facts" / f"{WRITER}.jsonl", records)
    return len(records)


def describe(planned: list[Planned]) -> list[str]:
    """One line per rule: `+ key: how` for a rule to add, `= key: why not` for the rest."""
    lines = []
    for item in planned:
        if item.add:
            how = f"enforced by {item.enforced_by}" if item.enforced_by else "advisory"
            why = "" if item.note == "advisory" else f" ({item.note})"
            lines.append(f"  + {item.rule.key}: {how}{why}")
        else:
            mark = "=" if item.detected else "-"
            lines.append(f"  {mark} {item.rule.key}: {item.note}")
    return lines


def apply(
    project, memdir: Path, wanted: list[str], dry_run: bool, files: Sequence[Preset] = ()
) -> tuple[int, list[str]]:
    """Plan and (unless dry_run) write the rules of the presets and preset files.

    Return how many rules are (or would be) added, and one line per rule.
    """
    from cairnkit.detect import detect
    from cairnkit.githook import guard_installed
    from cairnkit.rules import GUARDED

    guarded = GUARDED if guard_installed(project) else None
    planned = plan(memdir, resolve(wanted, files), guarded, detect(project.root))
    if not dry_run:
        write(memdir, planned)
    return sum(p.add for p in planned), describe(planned)


# `memory preset ...`


def run_list() -> int:
    for name in names():
        preset = load_preset(name)
        count = len(resolve([name]))
        extra = f"; includes {', '.join(preset.includes)}" if preset.includes else ""
        print(f"{name:<8} {count:>2} rule(s){extra}. {preset.summary}")
    print(f"{NONE:<8}  0 rule(s). No rule facts.")
    return 0


def run_show(name: str, detect_in=None) -> int:
    """Print the rules of a preset. With detect_in (a project), say what init would add there."""
    try:
        rules = resolve([name])
    except UnknownPreset as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Preset {name}: {len(rules)} rule(s).")
    if detect_in is not None:
        from cairnkit.detect import detect
        from cairnkit.githook import guard_installed
        from cairnkit.rules import GUARDED

        guarded = GUARDED if guard_installed(detect_in) else None
        planned = plan(None, rules, guarded, detect(detect_in.root))
        print(f"Detected in {detect_in.root} (+ added, - not added):")
        for line in describe(planned):
            print(line)
        return 0
    for rule in rules:
        cond = [f"only with {rule.when}"] if rule.when else []
        if rule.enforced_by:
            cond.append(f"{rule.enforced_by} when {rule.enforce_when} is found")
        extra = f" ({'; '.join(cond)})" if cond else ""
        print(f"- {rule.key} [{rule.area}] {rule.text}{extra}")
    return 0


def run_add(
    project, flag: str | None, wanted: list[str], dry_run: bool, paths: Sequence[str] = ()
) -> int:
    from cairnkit.paths import resolve_memory_dir

    if not wanted and not paths:
        print("error: name a preset, or a preset file with --file PATH", file=sys.stderr)
        return 1
    try:
        check_names(wanted)
        files = [load_file(path) for path in paths]
    except UnknownPreset as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    memdir, source = resolve_memory_dir(project, flag)
    if not (memdir / "facts").is_dir():
        print(f"error: no memory folder at {memdir} (from {source}); run `memory init`")
        return 1
    if dry_run:
        print("Dry run: nothing will change.")
    count, lines = apply(project, memdir, wanted, dry_run, files)
    if count and not dry_run:
        with contextlib.suppress(Exception):  # keep the agent task true to the memory
            from cairnkit import followups
            from cairnkit.memory import Memory

            followups.refresh(Memory.open(project, flag))
    if count:
        print(f"{'would add' if dry_run else 'add'} {count} rule fact(s) to {memdir / 'facts'}")
    for line in lines:
        print(line)
    if not count:
        print("Nothing to add.")
    return 0
