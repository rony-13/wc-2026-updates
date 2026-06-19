"""Provider selection.

Builds an ordered fallback chain based on configuration:

* If a football-data.org key is present, it is tried first (fastest updates),
  with openfootball behind it as a free, no-key safety net.
* With no key, openfootball alone is used — so the app runs out of the box with
  zero configuration and zero cost.

The CSV cache (handled in the service layer) sits behind the whole chain as the
final offline fallback.
"""
from __future__ import annotations

from typing import List

from .base import BaseProvider, ProviderError
from .football_data import FootballDataProvider
from .openfootball import OpenFootballProvider

__all__ = ["BaseProvider", "ProviderError", "build_provider_chain"]


def build_provider_chain(config) -> List[BaseProvider]:
    chain: List[BaseProvider] = []
    key = getattr(config, "FOOTBALL_DATA_API_KEY", "") or ""
    if key.strip():
        try:
            chain.append(FootballDataProvider(key.strip()))
        except ProviderError:
            pass
    chain.append(OpenFootballProvider(url=config.OPENFOOTBALL_URL))
    return chain
