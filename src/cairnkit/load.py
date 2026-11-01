"""`memory load`: print the facts a session needs, within a word budget.

This command never blocks a session: it always exits 0 and says plainly
when it read nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

from cairnkit import (
    enforcement,
    followups,
    hygiene,
    install_source,
    usage,
)
from cairnkit.check import read_health
from cairnkit.clock import now
from cairnkit.discover import DISCOVER
from cairnkit.envsecrets import EnvValues
from cairnkit.init import real_folder_warning
from cairnkit.memory import Memory, MemoryMissing
from cairnkit.paths import (
    Project,
    current_branch,
    default_branch,
    earlier_names,
    merged_checker,
    run_git,
    writer_name,
)
from cairnkit.secretscan import find_secrets
from cairnkit.selection import (
    AGENT_RULES,
    FRAME_FOOTER,
    FRAME_HEADER,
    areas_for_paths,
    branch_words,
    clean,
    name,
    owner_rule,
    pick,
    render,
    score_parts,
    words_in,
)
from cairnkit.state import effective_status

GIT_TIMEOUT = 1.0
NOTE_LINES = 8
TITLE = re.compile(r"# +\S")


def changed_paths(root: Path, branch: str | None) -> list[str]:
    """The files of the work in progress: uncommitted changes, and the branch's own diff."""
    uncommitted = run_git(root, "diff", "--name-only", "HEAD", timeout=GIT_TIMEOUT) or ""
    paths = uncommitted.splitlines()
    base = default_branch(root)
    if base and branch and base != branch:
        out = run_git(root, "diff", "--name-only", f"{base}...HEAD", timeout=GIT_TIMEOUT) or ""
        paths += [line for line in out.splitlines() if line not in paths]
    return paths


def note_head(path: Path, env: EnvValues | None = None) -> list[str]:
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError):
        return []
    except OSError:
        return [f"(This file could not be read: {path}.)"]
    body = [
        (number, line)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip() and not line.lstrip().startswith("<!--")
    ]
    # A first-line title names the file. `#96 is open` is no title, and a section heading gives a
    # list its meaning, so both stay.
    if body and TITLE.match(body[0][1]):
        body = body[1:]
    clipped = len(body) - NOTE_LINES
    more = (
        [f"({NOTE_LINES} of {len(body)} lines shown. The rest is in {path}.)"]
        if clipped > 0
        else []
    )
    shown = [
        f"line {number} withheld: looks like a secret ({', '.join(found)}); remove that line"
        if (found := find_secrets(line, env))
        else line
        for number, line in body[:NOTE_LINES]
    ]
    return shown + more


def active_states(memory: Memory) -> list[dict]:
    moment = now()
    is_merged = merged_checker(memory.project.root)
    active = []
    for state in memory.states.values():
        if effective_status(state, moment, is_merged)[0] == "active":
            active.append(state)
    return active


def build_output(memory: Memory, area: str | None, budget: int, explain: bool = False) -> list[str]:
    root = memory.project.root
    branch = current_branch(root)
    writer = writer_name(root)
    moment = now()
    states = active_states(memory)
    if area:
        states = [s for s in states if s.get("area") == area or s.get("pinned")]

    names = {branch} | earlier_names(root, branch)

    def mine(state: dict) -> bool:
        owner = state.get("until_branch_merged")
        return owner in names if owner else state.get("writer") == writer

    rules = [s for s in states if s.get("kind") == "rule"]
    states = [s for s in states if s.get("kind") != "rule"]
    short = [s for s in states if s.get("scope") == "short" and mine(s)]
    long = [s for s in states if s.get("scope", "long") == "long"]
    paths = changed_paths(root, branch)
    areas = areas_for_paths(paths, memory.config["areas"])
    words = branch_words(branch)

    used_at = usage.last_used(memory)
    short_budget = max(budget // 4, 1) if budget else 0
    short_shown = pick(short, short_budget, moment, areas, words, used_at)
    if short and not short_shown:
        short_shown = short[:1]
    used = sum(words_in(render(s)) for s in short_shown)
    long_budget = max(budget - used, 1) if budget else 0
    long_shown = pick(long, long_budget, moment, areas, words, used_at)

    out = [f"# Project memory ({memory.dir})"]
    if memory.errors:
        out.append(f"warning: {len(memory.errors)} bad line(s) skipped; run `memory repair`")
    stale = hygiene.hygiene_line(memory)
    if stale:
        out.append(stale)
    tidy_line = followups.pending_line(memory)
    if tidy_line:
        out.append(tidy_line)
    if memory.withheld:
        out.append("## Withheld facts (no person is needed for this)")
        out += [clean(f"- {memory.withheld_note(i)}") for i in sorted(memory.withheld)]
    rules.sort(key=lambda s: s.get("learned_at", ""))
    instructions = [s for s in rules if owner_rule(s)]
    false_claims = [s for s in instructions if enforcement.is_false(memory.project, s)]
    enforced = [s for s in instructions if s.get("enforced_by") and s not in false_claims]
    advisory = [s for s in instructions if not s.get("enforced_by")]
    if enforced:
        out.append("## Enforced rules (a check fails if broken)")
        out += [render(s) for s in enforced]
    if advisory or false_claims:
        out.append("## Advisory rules")
        out += [render(s) for s in advisory]
        out += [
            f"{render({**s, 'enforced_by': None})} (no check found for {name(s['enforced_by'])})"
            for s in false_claims
        ]
    out.append(FRAME_HEADER)
    agent_rules = [s for s in rules if not owner_rule(s)]
    if agent_rules:
        out.append(AGENT_RULES)
        out += [render(s) for s in agent_rules]
    pinned = [s for s in long_shown if s.get("pinned")]
    if pinned:
        out.append("## Pinned")
        out += [render(s) for s in sorted(pinned, key=lambda s: s.get("learned_at", ""))]
    if short_shown:
        out.append(f"## Short-term (branch {branch or writer})")
        out += [render(s) for s in sorted(short_shown, key=lambda s: s.get("learned_at", ""))]
    long_bullets = [s for s in long_shown if not s.get("pinned")]
    out.append("## Long-term")
    if not long_bullets:
        out.append("(no active long-term facts)")
    current = None
    for state in sorted(long_bullets, key=lambda s: (s.get("area", ""), s.get("happened_at", ""))):
        if state.get("area") != current:
            current = state.get("area")
            out.append(f"### {name(current)}")
        out.append(render(state))
    status = note_head(memory.dir / "notes" / "status.md", memory.env)
    if status:
        age = hygiene.commits_past_status(root, memory.dir / "notes" / "status.md")
        out.append(f"## Status (notes/status.md{age})")
        out += [f"- [status] {clean(x)}" for x in status]
    if branch:
        branch_note = note_head(memory.dir / "branches" / f"{branch}.md", memory.env)
        if branch_note:
            out.append(f"## Branch notes (branches/{branch}.md)")
            out += [f"- [branch] {clean(x)}" for x in branch_note]
    out.append(FRAME_FOOTER)
    hidden = len(short) + len(long) - len(short_shown) - len(long_shown)
    shown = len(rules) + len(short_shown) + len(long_shown)
    parts = [f"{shown} fact(s) shown"]
    if hidden > 0:
        parts.append(f"{hidden} active fact(s) not shown")
    out.append("; ".join(parts) + f". {DISCOVER}")
    if explain:
        shown_ids = {s["id"] for s in short_shown + long_shown}
        out += _explain(short + long, shown_ids, moment, areas, words, used_at)
    return out


def _explain(
    states: list[dict], shown: set[str], moment, areas: set[str], words: set[str], used_at: dict
) -> list[str]:
    out = [
        "## Ranking (--explain)",
        "Rules and pinned facts are always shown. Other facts are ranked by "
        "total = recency + kind + area + mention + trap + branch + use, until the word budget "
        "is used. A fact that does not fit stays active and searchable.",
    ]
    rows = []
    for state in states:
        if state.get("pinned"):
            continue
        parts = score_parts(state, moment, areas, words, used_at.get(state["id"]))
        rows.append((sum(parts.values()), state, parts))
    for total, state, parts in sorted(rows, key=lambda r: (-r[0], r[1]["id"])):
        detail = ", ".join(f"{name} {value:.2f}" for name, value in parts.items())
        verdict = "shown" if state["id"] in shown else "not shown"
        out.append(f"- [{state['id']}] total {total:.2f} ({detail}): {verdict}")
    return out


def run_load(
    project: Project,
    flag: str | None,
    area: str | None,
    budget: int,
    explain: bool = False,
    update_notice: bool = True,
) -> int:
    try:
        health = read_health(project, flag)
        if health.missing:
            print(health.answer())
            return 0
        memory = health.memory or Memory.open(project, flag)
        lines = build_output(memory, area, budget, explain)
        # Right under the header, so the agent sees them first. No detail from a stored record
        # goes here: this text is outside the frame that marks stored text as data.
        notice = install_source.notice_once() if update_notice else None
        warning = real_folder_warning(project, memory.dir)
        answer = [] if health.is_ok else [health.answer()]
        if health.errors or health.warnings:
            answer.append("`memory check` lists each one with its fix.")
        lines[1:1] = [line for line in (warning, notice, *answer, *health.todo) if line]
    except MemoryMissing as exc:
        print(f"memory: not loaded: {exc}")
        return 0
    except Exception as exc:
        print(f"memory: not loaded: unexpected error: {exc}")
        return 0
    print("\n".join([*health.linked, *lines]))
    return 0
