"""openfootball provider — free, public domain, no API key required.

Source: https://github.com/openfootball/worldcup.json (CC0 / public domain).
Updated by hand roughly once a day, so it is the zero-config default and the
reliable fallback, but not truly second-by-second live. For faster updates,
configure the football-data.org provider with a free key.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests

from ..models import Match, SCHEDULED, FINISHED
from .base import BaseProvider, ProviderError

DEFAULT_URL = (
    "https://raw.githubusercontent.com/openfootball/worldcup.json/"
    "master/2026/worldcup.json"
)

_OFFSET_RE = re.compile(r"UTC([+-]\d{1,2})(?::?(\d{2}))?")
_KNOCKOUT_ROUNDS = {
    "Round of 32": "LAST_32",
    "Round of 16": "LAST_16",
    "Quarter-final": "LAST_8",
    "Semi-final": "LAST_4",
    "Match for third place": "THIRD_PLACE",
    "Final": "FINAL",
}


def _parse_kickoff(date: str, time: str) -> str:
    """Turn '2026-06-18' + '19:00 UTC-6' into an ISO-8601 UTC string."""
    hhmm = time.split(" ", 1)[0]
    m = _OFFSET_RE.search(time)
    offset_hours = int(m.group(1)) if m else 0
    offset_min = int(m.group(2)) if (m and m.group(2)) else 0
    sign = 1 if offset_hours >= 0 else -1
    tz = timezone(sign * timedelta(hours=abs(offset_hours), minutes=offset_min))
    local = datetime.fromisoformat(f"{date}T{hhmm}:00").replace(tzinfo=tz)
    return local.astimezone(timezone.utc).isoformat()


def _stage_for(match: dict) -> str:
    if match.get("group"):
        return "GROUP_STAGE"
    return _KNOCKOUT_ROUNDS.get(match.get("round", ""), "KNOCKOUT")


class OpenFootballProvider(BaseProvider):
    name = "openfootball"
    min_interval_seconds = 60  # source refreshes ~daily; no need to poll faster

    def __init__(self, url: str = DEFAULT_URL, timeout: int = 15):
        self.url = url
        self.timeout = timeout

    def fetch_matches(self) -> List[Match]:
        try:
            resp = requests.get(self.url, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"openfootball fetch failed: {exc}") from exc

        matches: List[Match] = []
        for i, raw in enumerate(payload.get("matches", [])):
            score = raw.get("score") or {}
            ft = score.get("ft")
            et = score.get("et")  # cumulative score after extra time, if played
            pens = score.get("p")  # penalty-shootout score, if played
            # The final result is the extra-time score when present (it's
            # cumulative, not extra-time-only goals) -- using `ft` alone
            # here previously made any match that went to extra time look
            # tied even when it wasn't (e.g. a 1-1 at 90' that finished 2-1
            # after ET), which would have wrongly flagged it as
            # penalty-decided downstream.
            final = et if et else ft
            home_score: Optional[int] = final[0] if final else None
            away_score: Optional[int] = final[1] if final else None
            home_pens: Optional[int] = pens[0] if pens else None
            away_pens: Optional[int] = pens[1] if pens else None
            status = FINISHED if ft else SCHEDULED
            matches.append(
                Match(
                    id=str(raw.get("num", f"of-{i}")),
                    group=raw.get("group"),
                    stage=_stage_for(raw),
                    utc_date=_parse_kickoff(raw["date"], raw.get("time", "00:00 UTC+0")),
                    status=status,
                    home=raw.get("team1", "TBD"),
                    away=raw.get("team2", "TBD"),
                    home_score=home_score,
                    away_score=away_score,
                    home_penalty_score=home_pens,
                    away_penalty_score=away_pens,
                    venue=raw.get("ground"),
                )
            )
        if not matches:
            raise ProviderError("openfootball returned no matches")
        return matches
