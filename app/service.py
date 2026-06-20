"""Service layer: the single source of truth the web layer talks to.

Refresh strategy:
* **While a match is in progress** (live window) worldcup26.ir is authoritative
  real-time data and is polled every ``LIVE_POLL_SECONDS``. If it fails we keep
  retrying; we only drop to a fallback source after ``LIVE_FAIL_GRACE_SECONDS``
  of failure *and* only when we never managed to fetch real-time data for this
  game. Once we have real-time data for the game we persist it through outages
  (the fallback only updates after the match, so the last live snapshot is
  always the better answer).
* **Between matches** there is no live data to chase, so we poll slowly
  (``IDLE_POLL_SECONDS``) and keep whichever reachable source is *freshest*
  (carries the most completed results) — that may be worldcup26.ir or a fallback.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from .models import Match, LIVE, FINISHED
from .providers import build_provider_chain, ProviderError
from .standings import compute_standings
from .store import CsvStore

WORLDCUP26 = "worldcup26.ir"

# cadence / behaviour knobs
LIVE_POLL_SECONDS = 20        # how often to poll worldcup26.ir while a match runs
IDLE_POLL_SECONDS = 300       # how often to poll when nothing is in progress (5 min)
LIVE_FAIL_GRACE_SECONDS = 60  # keep retrying worldcup26.ir this long before falling back
MATCH_WINDOW_MINUTES = 130    # a kickoff keeps us in "live" mode this many minutes
PRE_KICKOFF_MINUTES = 2       # start live polling slightly before kickoff


class WorldCupService:
    def __init__(self, config):
        self.config = config
        self.providers = build_provider_chain(config)
        self.store = CsvStore(config.CACHE_DIR, config.SEED_DIR)
        self._lock = threading.Lock()
        self._matches: List[Match] = []
        self._source = "seed"
        self._provider_errors: dict = {}
        self._updated_at: Optional[str] = None
        self._tz = self._resolve_tz(config.TIMEZONE)

        # refresh bookkeeping
        self._last_cycle = 0.0          # timestamp of the last fetch cycle
        self._live_realtime_ok = False  # got worldcup26.ir data during this live window
        self._wc_fail_since: Optional[float] = None  # when worldcup26.ir began failing
        self._was_live = False
        self._wc = next((p for p in self.providers if p.name == WORLDCUP26), None)
        self._fallbacks = [p for p in self.providers if p.name != WORLDCUP26]

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
        """Scheduler entrypoint. Runs on a short tick; internally honours the
        live (20s) vs idle (5min) cadence and the source-selection rules."""
        now_dt = datetime.now(timezone.utc)
        now = now_dt.timestamp()
        live = self._live_now(now_dt)

        # New live window? reset the per-game failure/real-time tracking.
        if live and not self._was_live:
            self._live_realtime_ok = False
            self._wc_fail_since = None
        self._was_live = live

        interval = LIVE_POLL_SECONDS if live else IDLE_POLL_SECONDS
        if self._matches and (now - self._last_cycle) < interval:
            return False  # not time yet for this cadence
        self._last_cycle = now

        if live:
            ok = self._refresh_live(now)
        else:
            ok = self._refresh_idle(now)

        if not self._matches:
            self._bootstrap()
        return ok

    def _live_now(self, now_dt: datetime) -> bool:
        """Is a match in progress? True if anything is LIVE, or now falls inside
        a scheduled match window (so we ramp up polling right at kickoff)."""
        matches, _, _ = self._snapshot()
        for m in matches:
            if m.status == LIVE:
                return True
        pre = timedelta(minutes=PRE_KICKOFF_MINUTES)
        window = timedelta(minutes=MATCH_WINDOW_MINUTES)
        for m in matches:
            try:
                ko = m.kickoff()
            except Exception:  # noqa: BLE001 - bad date shouldn't break detection
                continue
            if (ko - pre) <= now_dt <= (ko + window):
                return True
        return False

    def _refresh_live(self, now: float) -> bool:
        """Match in progress: worldcup26.ir is authoritative; persist it through
        outages and only fall back after a sustained failure with no live data."""
        errors: dict = {}
        if self._wc is not None:
            try:
                matches = self._wc.fetch_matches()
            except ProviderError as exc:
                errors[self._wc.name] = str(exc)
                if self._wc_fail_since is None:
                    self._wc_fail_since = now
            else:
                self._commit(matches, self._wc.name, errors)
                self._live_realtime_ok = True
                self._wc_fail_since = None
                return True

        # worldcup26.ir failed this cycle.
        if self._live_realtime_ok:
            # Already have real-time data for this game — keep it. The fallback
            # only updates after the match, so it is never an improvement here.
            self._set_errors(errors)
            return False

        failing_for = (now - self._wc_fail_since) if self._wc_fail_since else 0.0
        if failing_for < LIVE_FAIL_GRACE_SECONDS:
            # Hold and keep retrying worldcup26.ir for up to a minute first.
            self._set_errors(errors)
            return False

        # Sustained outage and no real-time data this game -> use a fallback.
        for p in self._fallbacks:
            try:
                matches = p.fetch_matches()
            except ProviderError as exc:
                errors[p.name] = str(exc)
                continue
            self._commit(matches, p.name, errors)
            return True
        self._set_errors(errors)
        return False

    def _refresh_idle(self, now: float) -> bool:
        """No match in progress: poll slowly and keep whichever reachable source
        is freshest (carries the most completed results)."""
        errors: dict = {}
        candidates = []  # (freshness, prefers_worldcup26, name, matches)
        for p in self.providers:
            try:
                matches = p.fetch_matches()
            except ProviderError as exc:
                errors[p.name] = str(exc)
                continue
            prefers = 1 if p.name == WORLDCUP26 else 0
            candidates.append((self._freshness(matches), prefers, p.name, matches))
        if not candidates:
            self._set_errors(errors)
            return False
        # freshest wins; worldcup26.ir breaks ties (it's the real-time canonical).
        best = max(candidates, key=lambda c: (c[0], c[1]))
        self._commit(best[3], best[2], errors)
        return True

    # -- refresh helpers ---------------------------------------------------
    def _commit(self, matches: List[Match], source: str, errors: dict) -> None:
        self.store.save(matches, source)
        with self._lock:
            self._matches = matches
            self._source = source
            self._updated_at = self.store.meta().get("updated_at")
            self._provider_errors = errors

    def _set_errors(self, errors: dict) -> None:
        with self._lock:
            self._provider_errors = errors

    @staticmethod
    def _freshness(matches: List[Match]) -> Tuple[int, str]:
        """A cheap 'how up to date is this' score: number of completed results,
        tie-broken by the latest completed match date."""
        completed = [
            m for m in matches
            if m.status == FINISHED and m.home_score is not None and m.away_score is not None
        ]
        latest = max((m.utc_date or "" for m in completed), default="")
        return (len(completed), latest)

    # -- queries -----------------------------------------------------------
    def _snapshot(self) -> Tuple[List[Match], str, Optional[str]]:
        with self._lock:
            return list(self._matches), self._source, self._updated_at

    def _sports_day(self, dt: datetime) -> "date":
        """The 'sports day' a given local datetime belongs to: the calendar
        date rolls over at SPORTS_DAY_CUTOFF_HOUR (default 5am), not midnight,
        so an 11pm kickoff that finishes after midnight stays grouped with the
        evening it started, instead of vanishing from "Today" at 12:00am."""
        cutoff = getattr(self.config, "SPORTS_DAY_CUTOFF_HOUR", 5)
        if dt.hour < cutoff:
            dt = dt - timedelta(days=1)
        return dt.date()

    def get_today(self) -> dict:
        matches, source, updated_at = self._snapshot()
        sports_day = self._sports_day(datetime.now(self._tz))
        todays = [
            m for m in matches
            if self._sports_day(m.kickoff().astimezone(self._tz)) == sports_day
            or m.status == LIVE
        ]
        todays.sort(key=lambda m: m.kickoff())
        return {
            "date": sports_day.isoformat(),
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
