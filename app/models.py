"""Normalized data models shared across all providers.

Every provider, regardless of its upstream JSON shape, returns a list of
``Match`` objects. The rest of the app (standings, CSV cache, API, UI) only
ever speaks this vocabulary, so swapping or adding a data source never ripples
outward.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional

# Status values we normalize every provider down to.
SCHEDULED = "SCHEDULED"
LIVE = "LIVE"          # ball is rolling (in play / paused / half-time)
FINISHED = "FINISHED"

LIVE_STATUSES = {LIVE}


@dataclass
class Match:
    id: str
    group: Optional[str]          # "Group A" .. "Group L"; None for knockout
    stage: str                    # "GROUP_STAGE", "LAST_32", "FINAL", ...
    utc_date: str                 # ISO-8601 UTC, e.g. "2026-06-18T18:00:00+00:00"
    status: str                   # SCHEDULED | LIVE | FINISHED
    home: str
    away: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    minute: Optional[int] = None  # only meaningful while LIVE
    venue: Optional[str] = None
    home_scorers: list = field(default_factory=list)  # e.g. ["F. Balogun 31'", "F. Balogun 45'+5'"]
    away_scorers: list = field(default_factory=list)

    def kickoff(self) -> datetime:
        return datetime.fromisoformat(self.utc_date).astimezone(timezone.utc)

    def is_decided(self) -> bool:
        return (
            self.home_score is not None
            and self.away_score is not None
            and self.status in (LIVE, FINISHED)
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StandingRow:
    group: str
    team: str
    played: int = 0
    won: int = 0
    draw: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    rank: int = 0
    qualifies: bool = False       # top two of the group

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    def to_dict(self) -> dict:
        d = asdict(self)
        d["goal_difference"] = self.goal_difference
        return d
