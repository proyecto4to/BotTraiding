"""Injectable market-data seam for the regime refresh job (Fase 11).

The scheduler periodically POSTs /ai/regime/refresh; ai-engine then needs
bars for the configured symbols. There is no market-data service yet, so
the source is an injectable ``BarProvider`` (tests inject a synthetic
one; production will wire broker-connectors/market-data later - TODO).
When no provider is configured the refresh endpoint degrades gracefully
instead of failing the scheduler's job.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional

from trading_contracts import Bar


class BarProvider(ABC):
    @abstractmethod
    async def get_bars(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        """Most recent *limit* bars for symbol/timeframe, oldest first."""


_provider: Optional[BarProvider] = None


def get_bar_provider() -> Optional[BarProvider]:
    return _provider


def set_bar_provider(provider: Optional[BarProvider]) -> None:
    """Dependency-injection hook (tests / future market-data wiring)."""
    global _provider
    _provider = provider


def refresh_symbols() -> list[str]:
    """Symbols the periodic refresh should classify (env-configured)."""
    raw = os.environ.get("AI_REGIME_SYMBOLS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]
