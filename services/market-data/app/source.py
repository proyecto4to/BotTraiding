"""Upstream market-data source: broker-connectors historical klines.

A ``MarketDataSource`` is the injectable seam the poller and on-demand reads
use to fetch bars. The default implementation calls broker-connectors
(GET /connectors/{broker}/historical?symbol=&timeframe=&limit=), which for
binance returns real klines. Tests inject fakes so no network is required.
"""

from __future__ import annotations

import math
import os
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

import httpx

from trading_contracts import Bar

from . import config

_TIMEFRAME_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def _timeframe_seconds(timeframe: str) -> int:
    try:
        return int(timeframe[:-1]) * _TIMEFRAME_SECONDS[timeframe[-1]]
    except (KeyError, ValueError, IndexError):
        return 3600


class MarketDataSourceError(Exception):
    """Upstream could not provide bars (broker down, not connected, ...)."""


class MarketDataSource(ABC):
    @abstractmethod
    async def fetch(
        self, broker: str, symbol: str, timeframe: str, limit: int
    ) -> list[Bar]: ...


class BrokerConnectorsSource(MarketDataSource):
    def __init__(self, base_url: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url
        self._client = client

    @property
    def base_url(self) -> str:
        return (self._base_url or config.broker_connectors_url()).rstrip("/")

    async def fetch(
        self, broker: str, symbol: str, timeframe: str, limit: int
    ) -> list[Bar]:
        url = f"{self.base_url}/connectors/{broker}/historical"
        params = {"symbol": symbol, "timeframe": timeframe, "limit": limit}
        try:
            if self._client is not None:
                response = await self._client.get(url, params=params)
            else:
                async with httpx.AsyncClient(timeout=config.source_timeout()) as client:
                    response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise MarketDataSourceError(f"broker-connectors unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise MarketDataSourceError(
                f"broker-connectors returned {response.status_code} for "
                f"{broker}/{symbol}/{timeframe}: {response.text[:200]}"
            )
        return [Bar.model_validate(item) for item in response.json()]


class SyntheticMarketDataSource(MarketDataSource):
    """Time-anchored synthetic OHLCV so the platform runs end-to-end out of the
    box (demo / first run / no broker credentials).

    Each bar's price is a smooth deterministic function of its absolute
    time-bucket, so the series is reproducible AND evolves as real time passes
    (a new bar appears every timeframe). The overlapping sine trends produce the
    crossovers and reversions the strategies react to, so bots actually trade
    over time.
    """

    def _price_at(self, base: float, seed: int, n: int) -> float:
        trend = 0.16 * math.sin(n / 20.0) + 0.06 * math.sin(n / 7.0 + (seed % 7))
        wobble = 0.012 * math.sin(n * 1.3 + (seed % 11))
        return max(1.0, base * (1.0 + trend + wobble))

    async def fetch(
        self, broker: str, symbol: str, timeframe: str, limit: int
    ) -> list[Bar]:
        step = _timeframe_seconds(timeframe)
        seed = abs(hash(symbol))
        base = 100.0 + (seed % 400)
        last_n = int(datetime.now(timezone.utc).timestamp() // step)
        vol_rng = random.Random(seed)

        bars: list[Bar] = []
        for k in range(max(2, limit)):
            n = last_n - (limit - 1 - k)
            open_ = self._price_at(base, seed, n - 1)
            close = self._price_at(base, seed, n)
            high = max(open_, close) * 1.0015
            low = min(open_, close) * 0.9985
            ts = datetime.fromtimestamp(n * step, tz=timezone.utc)
            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    open=round(open_, 2),
                    high=round(high, 2),
                    low=round(low, 2),
                    close=round(close, 2),
                    volume=round(vol_rng.uniform(10, 100), 2),
                    timestamp=ts,
                )
            )
        return bars


def build_source() -> MarketDataSource:
    """Pick the upstream from MARKET_DATA_SOURCE (broker|synthetic).

    Default 'broker' (real klines via broker-connectors); 'synthetic' needs no
    broker and makes the bot work directly for demos and local runs."""
    if os.environ.get("MARKET_DATA_SOURCE", "broker").lower() == "synthetic":
        return SyntheticMarketDataSource()
    return BrokerConnectorsSource()
