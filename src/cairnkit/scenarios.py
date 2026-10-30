"""Ephemeral scenario lines for session load (L2 over L1 facts)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cairnkit.clock import parse_time
from cairnkit.selection import load_text, score, words_in

# Keep stale unlinked facts out of scenario lines so load does not advertise them.
STALE_DAYS = 90.0


@dataclass(frozen=True)
class ScenarioGroup:
    """Active long facts that share an area (and optionally a tag)."""

    label: str
    members: tuple[dict, ...]

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(m["id"] for m in self.members)


def _fresh_enough(state: dict, moment: datetime) -> bool:
    if state.get("pinned") or state.get("links"):
        return True
    try:
        age = (moment - parse_time(state["learned_at"])).total_seconds() / 86400
    except (KeyError, ValueError, TypeError):
        return True
    return age <= STALE_DAYS


def group_scenarios(
    states: list[dict],
    moment: datetime,
    areas: set[str],
    words: set[str],
    used: dict[str, datetime] | None = None,
) -> list[ScenarioGroup]:
    """Build scenario groups with at least two members. Best groups first."""
    used = used or {}
    by_key: dict[str, list[dict]] = {}
    for state in states:
        if state.get("scope", "long") != "long" or state.get("kind") == "rule":
            continue
        if not _fresh_enough(state, moment):
            continue
        area = str(state.get("area") or "general")
        tags = [str(t) for t in state.get("tags") or [] if str(t).strip()]
        key = f"{area}/{tags[0]}" if tags else area
        by_key.setdefault(key, []).append(state)
    groups = []
    for label, members in by_key.items():
        if len(members) < 2:
            continue
        ordered = tuple(
            sorted(
                members,
                key=lambda s: (
                    -score(s, moment, areas, words, used.get(s.get("id", ""))),
                    s.get("id", ""),
                ),
            )
        )
        groups.append(ScenarioGroup(label, ordered))
    groups.sort(
        key=lambda g: (
            -score(g.members[0], moment, areas, words, used.get(g.members[0].get("id", ""))),
            g.label,
        )
    )
    return groups


def render_scenario(group: ScenarioGroup, *, max_ids: int = 8) -> list[str]:
    """Two lines: label with ids, then a short lead from the top members."""
    shown = group.members[:max_ids]
    ids = ", ".join(m["id"] for m in shown)
    more = len(group.members) - len(shown)
    suffix = f" (+{more})" if more > 0 else ""
    lead = " · ".join(load_text(m) for m in shown[:2])
    return [f"- {group.label} | {ids}{suffix}", f"  {lead}"]


def scenario_cost(group: ScenarioGroup) -> int:
    return sum(words_in(line) for line in render_scenario(group))
