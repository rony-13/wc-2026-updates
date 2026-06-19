"""Compute live group standings from a list of matches.

Standings are always derived locally from match results rather than read from a
provider's standings endpoint. That keeps a single code path across providers
and means the tables move *live* as goals go in, not only when a match is
officially closed.

Tie-breaking uses points -> goal difference -> goals for -> team name. The full
FIFA ordering also includes head-to-head record and disciplinary/fair-play
points; those edge cases are noted in the README and intentionally not modeled
here to keep the logic transparent.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Dict, List

from .models import Match, StandingRow

QUALIFYING_POSITIONS = 2  # top two of each group advance


def _ensure_row(table: Dict[str, StandingRow], group: str, team: str) -> StandingRow:
    if team not in table:
        table[team] = StandingRow(group=group, team=team)
    return table[team]


def compute_standings(matches: List[Match]) -> "OrderedDict[str, List[StandingRow]]":
    """Return an ordered mapping of group name -> sorted list of StandingRow."""
    groups: Dict[str, Dict[str, StandingRow]] = {}

    for m in matches:
        if not m.group:
            continue  # knockout matches don't feed group tables
        table = groups.setdefault(m.group, {})
        home = _ensure_row(table, m.group, m.home)
        away = _ensure_row(table, m.group, m.away)

        if not m.is_decided():
            continue

        hs, as_ = m.home_score, m.away_score
        home.played += 1
        away.played += 1
        home.goals_for += hs
        home.goals_against += as_
        away.goals_for += as_
        away.goals_against += hs

        if hs > as_:
            home.won += 1
            away.lost += 1
            home.points += 3
        elif hs < as_:
            away.won += 1
            home.lost += 1
            away.points += 3
        else:
            home.draw += 1
            away.draw += 1
            home.points += 1
            away.points += 1

    result: "OrderedDict[str, List[StandingRow]]" = OrderedDict()
    for group in sorted(groups):
        rows = sorted(
            groups[group].values(),
            key=lambda r: (-r.points, -r.goal_difference, -r.goals_for, r.team),
        )
        for i, row in enumerate(rows, start=1):
            row.rank = i
            row.qualifies = i <= QUALIFYING_POSITIONS
        result[group] = rows
    return result
