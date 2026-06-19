"""Service layer: the single source of truth the web layer talks to.

Responsibilities:
* keep the latest normalized matches in memory (thread-safe);
* refresh them from the provider chain, respecting each provider's minimum
  poll interval, and fall back to the CSV cache when every provider fails;
* persist every successful fetch to CSV for offline loading;
* answer the two questions the UI asks: "what's on today?" and
  "what do the group tables look like right now?".
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from .models import Match, LIVE
from .providers import build_provider_chain, ProviderError
from .standings import compute_standings
from .store import CsvStore


class WorldCupService:
    def __init__(self, config):
        self.config = config
        self.providers = build_provider_chain(config)
        self.store = CsvStore(config.CACHE_DIR, config.SEED_DIR)
        self._lock = threading.Lock()
        self._matches: List[Match] = []
        self._source = "seed"
        self._updated_at: Optional[str] = None
        self._last_fetch: dict = {}  # provider name -> monotonic-ish timestamp
        self._tz = self._resolve_tz(config.TIMEZONE)
        self._bootstrap()

    # -- setup -------------------------------------------------------------
    @staticmethod
    def _resolve_tz(name: str):
        if name:
            try:
                return ZoneInfo(name)
            except Exception:  # noqa: BLE001 - bad tz name shouldn't crash app
                pass
        return datetime.now().astimezone().tzinfo  # server local tz

    def _bootstrap(self) -> None:
        """Load cache/seed immediately so the first page render has data."""
        cached = self.store.load()
        if cached:
            meta = self.store.meta()
            with self._lock:
                self._matches = cached
                self._source = meta.get("source", "cache")
                self._updated_at = meta.get("updated_at")

    # -- refresh -----------------------------------------------------------
    def refresh(self) -> bool:
        """Try each provider in order; cache and store the first that succeeds."""
        now = datetime.now(timezone.utc).timestamp()
        errors = []
        for provider in self.providers:
            last = self._last_fetch.get(provider.name, 0)
            if now - last < provider.min_interval_seconds and self._matches:
                continue  # too soon to re-poll this source
            try:
                matches = provider.fetch_matches()
            except ProviderError as exc:
                errors.append(str(exc))
                continue
            self._last_fetch[provider.name] = now
            self.store.save(matches, provider.name)
            with self._lock:
                self._matches = matches
                self._source = provider.name
                self._updated_at = self.store.meta().get("updated_at")
            return True

        # Everything failed (or was rate-limited with no data yet) -> use cache.
        if not self._matches:
            self._bootstrap()
        return False

    # -- queries -----------------------------------------------------------
    def _snapshot(self) -> Tuple[List[Match], str, Optional[str]]:
        with self._lock:
            return list(self._matches), self._source, self._updated_at

    def get_today(self) -> dict:
        matches, source, updated_at = self._snapshot()
        today = datetime.now(self._tz).date()
        todays = [
            m for m in matches
            if m.kickoff().astimezone(self._tz).date() == today or m.status == LIVE
        ]
        todays.sort(key=lambda m: m.kickoff())
        return {
            "date": today.isoformat(),
            "source": source,
            "updated_at": updated_at,
            "matches": [self._match_view(m) for m in todays],
        }

    def get_teams(self) -> List[str]:
        """Sorted unique nation names from the group stage (no '2A' placeholders)."""
        matches, _, _ = self._snapshot()
        names = set()
        for m in matches:
            if m.group:  # group-stage matches have real nation names
                names.add(m.home)
                names.add(m.away)
        return sorted(names)

    def get_groups(self) -> dict:
        matches, source, updated_at = self._snapshot()
        tables = compute_standings(matches)
        return {
            "source": source,
            "updated_at": updated_at,
            "groups": [
                {"group": g, "rows": [r.to_dict() for r in rows]}
                for g, rows in tables.items()
            ],
        }

    def _match_view(self, m: Match) -> dict:
        d = m.to_dict()
        d["kickoff_local"] = m.kickoff().astimezone(self._tz).strftime("%H:%M")
        d["is_live"] = m.status == LIVE
        return d
