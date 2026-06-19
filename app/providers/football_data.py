"""football-data.org provider — faster live updates, free API key required.

Get a free key at https://www.football-data.org/client/register and put it in
your local .env as FOOTBALL_DATA_API_KEY (never commit it). Free tier allows
10 requests/minute, which is ample because the backend caches and the frontend
only ever polls the local backend.

Docs: https://www.football-data.org/documentation/api  (competition code "WC")
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import requests

from ..models import Match, SCHEDULED, LIVE, FINISHED
from .base import BaseProvider, ProviderError

MATCHES_URL = "https://api.football-data.org/v4/competitions/WC/matches"

# football-data.org status -> our normalized status
_STATUS_MAP = {
    "SCHEDULED": SCHEDULED,
    "TIMED": SCHEDULED,
    "IN_PLAY": LIVE,
    "PAUSED": LIVE,
    "SUSPENDED": LIVE,
    "FINISHED": FINISHED,
    "AWARDED": FINISHED,
}


def _normalize_group(raw_group: Optional[str]) -> Optional[str]:
    """'GROUP_A' -> 'Group A'; leave knockout/None alone."""
    if not raw_group:
        return None
    parts = raw_group.replace("_", " ").title().split()
    if parts and parts[0] == "Group":
        return " ".join(parts)
    return None


def _to_utc_iso(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt.astimezone(timezone.utc).isoformat()


class FootballDataProvider(BaseProvider):
    name = "football-data.org"
    min_interval_seconds = 12  # comfortably under the 10 req/min free tier

    def __init__(self, api_key: str, timeout: int = 15):
        if not api_key:
            raise ProviderError("football-data.org requires an API key")
        self.api_key = api_key
        self.timeout = timeout

    def fetch_matches(self) -> List[Match]:
        try:
            resp = requests.get(
                MATCHES_URL,
                headers={"X-Auth-Token": self.api_key},
                timeout=self.timeout,
            )
            if resp.status_code == 429:
                raise ProviderError("football-data.org rate limit hit (429)")
            if resp.status_code in (401, 403):
                raise ProviderError("football-data.org auth failed; check your key")
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"football-data.org fetch failed: {exc}") from exc

        matches: List[Match] = []
        for raw in payload.get("matches", []):
            score = (raw.get("score") or {}).get("fullTime") or {}
            status = _STATUS_MAP.get(raw.get("status", ""), SCHEDULED)
            matches.append(
                Match(
                    id=str(raw.get("id")),
                    group=_normalize_group(raw.get("group")),
                    stage=raw.get("stage", "GROUP_STAGE"),
                    utc_date=_to_utc_iso(raw["utcDate"]),
                    status=status,
                    home=(raw.get("homeTeam") or {}).get("name") or "TBD",
                    away=(raw.get("awayTeam") or {}).get("name") or "TBD",
                    home_score=score.get("home"),
                    away_score=score.get("away"),
                    minute=raw.get("minute"),
                )
            )
        if not matches:
            raise ProviderError("football-data.org returned no matches")
        return matches
