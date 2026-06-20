"""Configuration, loaded from environment variables (and a local .env).

Secrets only ever come from the environment. .env is git-ignored; .env.example
documents every knob. Nothing here ever prints or logs the API key.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()  # reads .env if present; real env vars take precedence

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _as_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    # --- secrets ---------------------------------------------------------
    FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")

    # --- data source -----------------------------------------------------
    OPENFOOTBALL_URL = os.environ.get(
        "OPENFOOTBALL_URL",
        "https://raw.githubusercontent.com/openfootball/worldcup.json/"
        "master/2026/worldcup.json",
    )

    # --- refresh cadence (seconds) --------------------------------------
    # How often the backend pulls from upstream. The frontend polls the local
    # backend independently (today=30s, groups=60s) and always gets cached data
    # instantly, so this can stay gentle on the upstream rate limits.
    REFRESH_SECONDS = _as_int("REFRESH_SECONDS", 20)

    # --- server ----------------------------------------------------------
    HOST = os.environ.get("HOST", "127.0.0.1")
    # Set PUBLIC_READONLY=1 when exposing this to the public internet (e.g.
    # behind a Cloudflare Tunnel): visitors can view everything but cannot
    # change the favorite/following teams -- only the host, editing
    # data/cache/preferences.json directly on the VM, can.
    PUBLIC_READONLY = os.environ.get("PUBLIC_READONLY", "0").strip() == "1"
    PORT = _as_int("PORT", 8765)
    TIMEZONE = os.environ.get("DISPLAY_TIMEZONE", "")  # "" -> server local time
    # A FINISHED match stays under "Today" for this many hours after kickoff,
    # even once its kickoff calendar-date has technically rolled into
    # "yesterday" -- see service.get_today() for why this replaced a fixed
    # rollover hour (no single local hour is fair to every timezone, since
    # North America's host window lands very differently around the world).
    LATE_MATCH_GRACE_HOURS = _as_int("LATE_MATCH_GRACE_HOURS", 4)

    # --- paths -----------------------------------------------------------
    BASE_DIR = _BASE_DIR
    CACHE_DIR = os.path.join(_BASE_DIR, "data", "cache")
    SEED_DIR = os.path.join(_BASE_DIR, "data", "seed")
