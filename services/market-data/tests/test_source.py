"""BrokerConnectorsSource: parses klines from broker-connectors, maps errors."""

from __future__ import annotations

import httpx
import pytest

from app.source import BrokerConnectorsSource, MarketDataSourceError


def _bar_json(symbol, timeframe):
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "open": 1.0,
        "high": 2.0,
        "low": 0.5,
        "close": 1.5,
        "volume": 100.0,
        "timestamp": "2026-01-01T00:00:00Z",
    }


async def test_fetch_parses_bars():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/connectors/binance/historical"
        assert request.url.params["symbol"] == "BTCUSD"
        assert request.url.params["limit"] == "5"
        return httpx.Response(200, json=[_bar_json("BTCUSD", "1h")])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock")
    source = BrokerConnectorsSource(base_url="http://mock", client=client)

    bars = await source.fetch("binance", "BTCUSD", "1h", 5)
    assert len(bars) == 1
    assert bars[0].symbol == "BTCUSD" and bars[0].close == 1.5


async def test_fetch_maps_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, text="not connected")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock")
    source = BrokerConnectorsSource(base_url="http://mock", client=client)

    with pytest.raises(MarketDataSourceError):
        await source.fetch("binance", "BTCUSD", "1h", 5)


async def test_fetch_maps_transport_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock")
    source = BrokerConnectorsSource(base_url="http://mock", client=client)

    with pytest.raises(MarketDataSourceError):
        await source.fetch("binance", "BTCUSD", "1h", 5)
