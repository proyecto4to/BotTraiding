"""Upstream market-data source: broker-connectors historical klines.

A ``MarketDataSource`` is the injectable seam the poller and on-demand reads
use to fetch bars. The default implementation calls broker-connectors
(GET /connectors/{broker}/historical?symbol=&timeframe=&limit=), which for
binance returns real klines. Tests inject fakes so no network is required.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from trading_contracts import Bar

from . import config


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
