"""Provider interface.

A provider's only job is to return a normalized list of ``Match`` objects.
Anything provider-specific (auth, URL shape, JSON quirks, timezone parsing)
stays inside the provider module.
"""
from __future__ import annotations

from typing import List

from ..models import Match


class ProviderError(RuntimeError):
    """Raised when a provider cannot return data (network, auth, rate limit)."""


class BaseProvider:
    name = "base"
    #: minimum seconds between real upstream calls; the service layer respects
    #: this so we never hammer a source faster than it actually updates.
    min_interval_seconds = 30

    def fetch_matches(self) -> List[Match]:  # pragma: no cover - interface
        raise NotImplementedError
