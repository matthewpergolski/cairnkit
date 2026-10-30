"""`memory load`: print the facts a session needs, within a word budget.

This command never blocks a session: it always exits 0 and says plainly
when it read nothing.
"""

from __future__ import annotations

from pathlib import Path

from cairnkit import followups, hygiene, install_source, refresh, scenarios, skills, usage
from cairnkit.clock import now
from cairnkit.discover import DISCOVER
from cairnkit.init import link_here
from cairnkit.memory import Memory, MemoryMissing
from cairnkit.paths import (
    LINK_NAME,
    Project,
    current_branch,
    default_branch,
    merged_checker,
    run_git,
    writer_name,
)
from cairnkit.selection import (
    FRAME_FOOTER,
    FRAME_HEADER,
    areas_for_paths,
    branch_words,
    clean,
    pick,
    render,
    score_parts,
    words_in,
)
from cairnkit.state import effective_status

GIT_TIMEOUT = 1.0
NOTE_LINES = 8


def changed_paths(root: Path, branch: str | None) -> list[str]:
    base = default_branch(root)
    if not base or not branch or base == branch:
        return []
    out = run_git(root, "diff", "--name-only", f"{base}...HEAD", timeout=GIT_TIMEOUT)
    return out.splitlines() if out else []


def note_head(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    body = [
        line
        for line in lines
        if line.strip() and not line.startswith("#") and not line.lstrip().startswith("<!--")
    ]
    return body[:NOTE_LINES]


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

    def mine(state: dict) -> bool:
        owner = state.get("until_branch_merged")
        return owner == branch if owner else state.get("writer") == writer

    rules = [s for s in states if s.get("kind") == "rule"]
    states = [s for s in states if s.get("kind") != "rule"]
    short = [s for s in states if s.get("scope") == "short" and mine(s)]
    long = [s for s in states if s.get("scope", "long") == "long"]
    paths = changed_paths(root, branch)
    areas = areas_for_paths(paths, memory.config["areas"])
    words = branch_words(branch)

    used_at = usage.last_used(memory)
    groups = scenarios.group_scenarios(long, moment, areas, words, used_at)
    scenario_budget = max(budget // 3, 1) if budget else 0
    scenarios_shown = []
    used = 0
    covered: set[str] = set()
    for group in groups:
        cost = scenarios.scenario_cost(group)
        if budget and used + cost > scenario_budget and scenarios_shown:
            continue
        if budget and used + cost > budget:
            continue
        scenarios_shown.append(group)
        used += cost
        covered.update(group.ids)

    short_budget = max(budget // 4, 1) if budget else 0
    short_shown = pick(short, short_budget, moment, areas, words, used_at)
    if short and not short_shown:
        short_shown = short[:1]
    used += sum(words_in(render(s)) for s in short_shown)
    # Prefer uncovered long facts for remaining bullets; pinned always included.
    long_rest = [s for s in long if s["id"] not in covered or s.get("pinned")]
    long_budget = max(budget - used, 1) if budget else 0
    long_shown = pick(long_rest, long_budget, moment, areas, words, used_at)
    folded = len(covered - {s["id"] for s in long_shown})

    out = [f"# Project memory ({memory.dir})"]
    if memory.errors:
        out.append(f"warning: {len(memory.errors)} bad line(s) skipped; run `memory check`")
    stale = hygiene.hygiene_line(memory)
    if stale:
        out.append(stale)
    if _followup_pending(memory):
        out.append(f"Migration follow-up pending: see {LINK_NAME}/proposals/migrate-followups.md")
    tidy_line = followups.pending_line(memory)
    if tidy_line:
        out.append(tidy_line)
    rules.sort(key=lambda s: s.get("learned_at", ""))
    enforced = [s for s in rules if s.get("enforced_by")]
    advisory = [s for s in rules if not s.get("enforced_by")]
    if enforced:
        out.append("## Enforced rules (a check fails if broken)")
        out += [render(s) for s in enforced]
    if advisory:
        out.append("## Advisory rules")
        out += [render(s) for s in advisory]
    out.append(FRAME_HEADER)
    pinned = [s for s in long_shown if s.get("pinned")]
    if pinned:
        out.append("## Pinned")
        out += [render(s) for s in sorted(pinned, key=lambda s: s.get("learned_at", ""))]
    if scenarios_shown:
        out.append("## Scenarios")
        for group in scenarios_shown:
            out += scenarios.render_scenario(group)
    if short_shown:
        out.append(f"## Short-term (branch {branch or writer})")
        out += [render(s) for s in sorted(short_shown, key=lambda s: s.get("learned_at", ""))]
    long_bullets = [s for s in long_shown if not s.get("pinned")]
    out.append("## Long-term")
    if not long_bullets:
        out.append("(no active long-term facts)" if not long_shown else "(covered in scenarios)")
    current = None
    for state in sorted(long_bullets, key=lambda s: (s.get("area", ""), s.get("happened_at", ""))):
        if state.get("area") != current:
            current = state.get("area")
            out.append(f"### {clean(current)}")
        out.append(render(state))
    status = note_head(memory.dir / "notes" / "status.md")
    if status:
        out += ["## Status (notes/status.md)", *(f"- [status] {clean(x)}" for x in status)]
    if branch:
        branch_note = note_head(memory.dir / "branches" / f"{branch}.md")
        if branch_note:
            out.append(f"## Branch notes (branches/{branch}.md)")
            out += [f"- [branch] {clean(x)}" for x in branch_note]
    out.append(FRAME_FOOTER)
    hidden = len(short) + len(long) - len(short_shown) - len(long_shown) - folded
    shown = len(rules) + len(short_shown) + len(long_shown)
    parts = [f"{shown} fact(s) shown"]
    if folded:
        parts.append(f"{folded} folded into scenarios")
    if hidden > 0:
        parts.append(f"{hidden} active fact(s) not shown")
    out.append("; ".join(parts) + f". Open one with `memory show ID`. {DISCOVER}")
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
        "total = recency + kind + area + branch + use, until the word budget is used.",
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


def _followup_pending(memory: Memory) -> bool:
    """True while the task that `memory migrate` wrote is not done."""
    path = memory.dir / "proposals" / "migrate-followups.md"
    try:
        with path.open(encoding="utf-8") as fh:
            return fh.readline().startswith("# Migration follow-up (pending)")
    except OSError:
        return False


def run_load(
    project: Project,
    flag: str | None,
    area: str | None,
    budget: int,
    explain: bool = False,
    agent: str | None = None,
    record: bool = False,
) -> int:
    try:
        linked = link_here(project, flag)
        memory = Memory.open(project, flag)
        lines = build_output(memory, area, budget, explain)
        # Right under the header, so the agent sees them first.
        lines[1:1] = [
            line
            for line in (install_source.update_line(), refresh.repo_line(project, flag))
            if line
        ]
    except MemoryMissing as exc:
        print(f"memory: not loaded: {exc}")
        return 0
    except Exception as exc:
        print(f"memory: not loaded: unexpected error: {exc}")
        return 0
    if linked:
        print(linked)
    print("\n".join(lines))
    line = skills.session_line(memory.dir, agent, record)
    if line:
        print(line)
    return 0
