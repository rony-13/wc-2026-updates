"""Provider selection.

Builds an ordered fallback chain:

1. **worldcup26.ir** — free, no key, *real-time* live scores (primary). Disable
   with the env var ``WC26_LIVE=0`` if you ever want to skip it.
2. **football-data.org** — only if an API key is set. Note its free tier serves
   *delayed* (not live) scores; live scores there require a paid plan.
3. **openfootball** — free, no key, but updated only ~daily (final scores only).

Each provider returns a normalized match list; the first that succeeds wins, and
the CSV cache (in the service layer) sits behind them all as the offline
fallback. If a provider errors or returns nothing, the next one is tried — so a
hiccup at worldcup26.ir silently falls back to openfootball, exactly as before.
"""
from __future__ import annotations

import os
from typing import List

from .base import BaseProvider, ProviderError
from .football_data import FootballDataProvider
from .openfootball import OpenFootballProvider
from .worldcup26 import WorldCup26Provider

__all__ = ["BaseProvider", "ProviderError", "build_provider_chain"]


def build_provider_chain(config) -> List[BaseProvider]:
    chain: List[BaseProvider] = []

    # 1. Real-time, free, no key — unless explicitly disabled.
    if os.environ.get("WC26_LIVE", "1").strip() != "0":
        chain.append(WorldCup26Provider(seed_dir=getattr(config, "SEED_DIR", None)))

    # 2. football-data.org, only when a key is configured.
    key = getattr(config, "FOOTBALL_DATA_API_KEY", "") or ""
    if key.strip():
        try:
            chain.append(FootballDataProvider(key.strip()))
        except ProviderError:
            pass

    # 3. Always-available free fallback (~daily updates).
    chain.append(OpenFootballProvider(url=config.OPENFOOTBALL_URL))
    return chain
