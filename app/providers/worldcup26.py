"""worldcup26.ir provider — free, no API key, real-time live scores.

Source: https://worldcup26.ir  (repo: github.com/rezarahiminia/worldcup2026)
A community, open-source API built specifically for the 2026 World Cup that
updates match scores and status live during the tournament. Read access needs
no key, so this is the zero-cost way to get true in-match scores — unlike the
football-data.org *free* tier, whose scores are delayed, not live.

We only call /get/games (it carries English team names, the group letter, the
running score, a `finished` flag and `time_elapsed`), and compute standings
locally as usual.

Caveat: the feed's `local_date` has no timezone, so kickoff *clock* times for
not-yet-started matches are interpreted with a fixed offset (US Eastern by
default, override with WC26_TZ_OFFSET). This affects only the displayed kickoff
time and the "today" boundary at the margins — never live scores or standings.
Live matches are always shown regardless of date.
"""
from __future__ import annotations

import csv
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import requests

from ..models import Match, SCHEDULED, LIVE, FINISHED
from .base import BaseProvider, ProviderError

GAMES_URL = "https://worldcup26.ir/get/games"

_GROUP_LETTERS = set("ABCDEFGHIJKL")
_KNOCKOUT_STAGE = {
    "R32": "LAST_32", "R16": "LAST_16", "QF": "LAST_8",
    "SF": "LAST_4", "3RD": "THIRD_PLACE", "FINAL": "FINAL",
}
_NOT_STARTED = {"", "notstarted", "not_started", "ns", "scheduled", "upcoming", "tbd"}

# worldcup26.ir and the seed schedule (openfootball) sometimes spell the same
# team differently -- normalize before the trusted-schedule team-pair lookup
# so e.g. venue cross-referencing isn't silently missed over a spelling diff.
_NAME_ALIASES = {
    "united states": "usa",
    "bosnia and herzegovina": "bosnia & herzegovina",
    "democratic republic of the congo": "dr congo",
}


def _norm_name(name: str) -> str:
    key = name.strip().lower()
    return _NAME_ALIASES.get(key, key)


def _to_int(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _status(finished: str, time_elapsed: str) -> str:
    if str(finished).strip().upper() == "TRUE":
        return FINISHED
    if str(time_elapsed).strip().lower() in _NOT_STARTED:
        return SCHEDULED
    return LIVE


def _minute(time_elapsed: str) -> Optional[int]:
    digits = "".join(ch for ch in str(time_elapsed) if ch.isdigit())
    return int(digits) if digits else None


def _kickoff_iso(local_date: str, offset_hours: int) -> str:
    # "06/11/2026 13:00" with no tz -> apply the assumed offset, return UTC ISO.
    # Fallback only: the feed's local_date carries no per-venue timezone, so this
    # single fixed offset is wrong for non-Eastern venues (Pacific/Central). We
    # prefer the cross-referenced seed lookup in _load_trusted_kickoffs() below;
    # this only fires for fixtures that lookup can't resolve (e.g. knockout
    # matchups not yet present in the seed).
    try:
        naive = datetime.strptime(local_date.strip(), "%m/%d/%Y %H:%M")
        tz = timezone(timedelta(hours=offset_hours))
        return naive.replace(tzinfo=tz).astimezone(timezone.utc).isoformat()
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc).isoformat()


def _load_trusted_schedule(seed_dir: Optional[str]) -> Dict[Tuple[str, str], dict]:
    """Build a {sorted(team_pair): {"utc_date": ..., "venue": ...}} lookup
    from the bundled seed schedule (data/seed/matches.csv, sourced from
    openfootball, which parses each match's real per-venue UTC offset
    correctly and carries venue names worldcup26.ir's feed doesn't expose
    -- it only gives an opaque `stadium_id` with no name lookup of its own).

    worldcup26.ir's `local_date` has no timezone marker, so a fixed assumed
    offset is wrong for any venue outside it (e.g. Pacific/Central games are
    off by 1-3 hours) -- which can flip which calendar day a match falls on
    right around midnight. Since the tournament schedule is fixed and known in
    advance, cross-referencing by team pair sidesteps the guess entirely for
    every group-stage fixture (and fills in venue for free). Knockout
    pairings not yet in the seed simply fall back to the offset guess for
    kickoff time and have no venue (see _kickoff_iso).
    """
    lookup: Dict[Tuple[str, str], dict] = {}
    if not seed_dir:
        return lookup
    path = os.path.join(seed_dir, "matches.csv")
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                home = (row.get("home") or "").strip()
                away = (row.get("away") or "").strip()
                utc_date = (row.get("utc_date") or "").strip()
                venue = (row.get("venue") or "").strip()
                if home and away and utc_date:
                    key = tuple(sorted((_norm_name(home), _norm_name(away))))
                    lookup.setdefault(key, {"utc_date": utc_date, "venue": venue or None})
    except (OSError, csv.Error):
        pass  # missing/unreadable seed -> just fall back to the offset guess
    return lookup


def _parse_scorers(raw) -> list:
    """Parse worldcup26.ir's `home_scorers`/`away_scorers` fields, e.g.
    '{"F. Balogun 31\'","F. Balogun 45\'+5\'"}' -> ["F. Balogun 31'", ...].

    This is a Postgres text-array literal dumped as a string, not JSON.
    Quoting is inconsistent across records (straight " vs curly “ ” -- one
    real record even mixes both directions within the same string), so we
    strip any quote-like character per element rather than match specific
    open/close pairs.
    """
    if not raw or str(raw).strip().lower() == "null":
        return []
    text = str(raw).strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1]
    parts = text.split(",")
    cleaned = [p.strip(" \"\u201c\u201d") for p in parts]
    return [p for p in cleaned if p]


class WorldCup26Provider(BaseProvider):
    name = "worldcup26.ir"
    min_interval_seconds = 15  # real-time source; poll briskly but politely

    def __init__(self, timeout: int = 20, tz_offset: Optional[int] = None,
                 seed_dir: Optional[str] = None):
        self.timeout = timeout
        self._trusted_schedule = _load_trusted_schedule(seed_dir)
        if tz_offset is None:
            try:
                tz_offset = int(os.environ.get("WC26_TZ_OFFSET", "-4"))
            except ValueError:
                tz_offset = -4
        self.tz_offset = tz_offset

    def _get_payload(self) -> dict:
        """GET the games feed, retrying once — the free API can be slow under
        heavy load during live matches, and a single timeout shouldn\'t drop us
        to the non-live fallback."""
        last_exc = None
        for attempt in range(2):
            try:
                resp = requests.get(
                    GAMES_URL,
                    headers={
                        "Accept": "application/json",
                        # default python-requests UA is frequently blocked (403) by
                        # WAFs/rate-limiters; present a browser-like UA instead.
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36"
                        ),
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(1.0)
        raise ProviderError(f"worldcup26.ir fetch failed after retry: {last_exc}")

    def fetch_matches(self) -> List[Match]:
        payload = self._get_payload()
        games = payload.get("games")
        if not isinstance(games, list) or not games:
            raise ProviderError("worldcup26.ir returned no games")

        matches: List[Match] = []
        skipped = 0
        for g in games:
            group_raw = str(g.get("group", "")).strip().upper()
            is_group = (str(g.get("type", "")).lower() == "group") or (group_raw in _GROUP_LETTERS)
            group = f"Group {group_raw}" if (is_group and group_raw in _GROUP_LETTERS) else None
            stage = "GROUP_STAGE" if group else _KNOCKOUT_STAGE.get(group_raw, "KNOCKOUT")

            home = (g.get("home_team_name_en") or "").strip()
            away = (g.get("away_team_name_en") or "").strip()
            # Knockout fixtures not yet decided carry a descriptive placeholder
            # instead of a real team name (e.g. "Runner-up Group B") -- show
            # that rather than a bare "TBD".
            home = home or (g.get("home_team_label") or "").strip() or "TBD"
            away = away or (g.get("away_team_label") or "").strip() or "TBD"

            # A real group game must carry team names. Skip a malformed record
            # rather than failing the whole fetch (one bad row used to drop us
            # to the non-live fallback).
            if is_group and (home == "TBD" or away == "TBD"):
                skipped += 1
                continue

            trusted = self._trusted_schedule.get(tuple(sorted((_norm_name(home), _norm_name(away)))))
            status = _status(g.get("finished", "FALSE"), g.get("time_elapsed", ""))
            if status == SCHEDULED:
                home_score = away_score = None  # ignore 0–0 placeholders before kickoff
            else:
                home_score = _to_int(g.get("home_score"))
                away_score = _to_int(g.get("away_score"))

            matches.append(
                Match(
                    id=str(g.get("id", "")),
                    group=group,
                    stage=stage,
                    utc_date=(trusted or {}).get("utc_date") or _kickoff_iso(g.get("local_date", ""), self.tz_offset),
                    status=status,
                    home=home,
                    away=away,
                    home_score=home_score,
                    away_score=away_score,
                    minute=_minute(g.get("time_elapsed", "")) if status == LIVE else None,
                    venue=(trusted or {}).get("venue"),
                    home_scorers=_parse_scorers(g.get("home_scorers")),
                    away_scorers=_parse_scorers(g.get("away_scorers")),
                )
            )
        if not matches:
            raise ProviderError(f"worldcup26.ir had no usable games ({skipped} skipped)")
        return matches
