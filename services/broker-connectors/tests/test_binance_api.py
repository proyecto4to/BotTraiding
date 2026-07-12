"""FastAPI surface tests for the real Binance connector (mock transport)."""

from __future__ import annotations

from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from app.connectors.http_base import BrokerConfig
from app.main import app
from app.registry import registry

from .binance_mocks import BinanceMockAPI, make_binance_client
from .conftest import default_handler, make_mock_client

client = TestClient(app)


def seed_binance(mock_api: BinanceMockAPI | None = None) -> BinanceMockAPI:
    """Register a binance connector wired to the Binance-shaped mock, then
    connect it through the public API (as trading-engine would)."""
    mock_api = mock_api or BinanceMockAPI()
    config = BrokerConfig(broker="binance", api_key="k", api_secret="s", demo=True)
    registry.get_or_create("binance", config, client=make_binance_client(mock_api))
    response = client.post(
        "/connectors/binance/connect", json={"api_key": "k", "api_secret": "s", "demo": True}
    )
    assert response.status_code == 200 and response.json()["connected"] is True
    return mock_api


def test_historical_with_limit_returns_real_klines():
    mock_api = seed_binance()

    response = client.get(
        "/connectors/binance/historical",
        params={"symbol": "BTCUSDT", "timeframe": "1h", "limit": 2},
    )

    assert response.status_code == 200
    bars = response.json()
    assert len(bars) == 2
    assert bars[0]["symbol"] == "BTCUSDT"
    assert bars[0]["open"] == 42000.0
    assert bars[0]["close"] == 42250.0
    kline_request = mock_api.requests_for("GET", "/api/v3/klines")[0]
    assert kline_request.url.params["interval"] == "1h"
    assert kline_request.url.params["limit"] == "2"


def test_historical_with_start_end_returns_real_klines():
    seed_binance()
    response = client.get(
        "/connectors/binance/historical",
        params={
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T02:00:00Z",
        },
    )
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_historical_requires_range_or_limit():
    seed_binance()
    response = client.get(
        "/connectors/binance/historical", params={"symbol": "BTCUSDT", "timeframe": "1h"}
    )
    assert response.status_code == 422


def test_historical_limit_unsupported_for_stub_connectors():
    config = BrokerConfig(broker="bybit", demo=True)
    registry.get_or_create("bybit", config, client=make_mock_client(default_handler))
    client.post("/connectors/bybit/connect", json={"demo": True})

    response = client.get(
        "/connectors/bybit/historical",
        params={"symbol": "BTCUSDT", "timeframe": "1h", "limit": 5},
    )
    assert response.status_code == 422
    assert "does not support" in response.json()["detail"]


def test_historical_unknown_timeframe_maps_to_422():
    seed_binance()
    response = client.get(
        "/connectors/binance/historical",
        params={"symbol": "BTCUSDT", "timeframe": "13m", "limit": 1},
    )
    assert response.status_code == 422
    assert "13m" in response.json()["detail"]


def test_place_order_via_api_hits_real_endpoint_shape():
    mock_api = seed_binance()
    response = client.post(
        "/connectors/binance/orders",
        json={
            "id": str(uuid4()),
            "signal_id": str(uuid4()),
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.5,
            "order_type": "market",
            "account_id": "default",
            "execution_mode": "paper",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "filled"
    assert body["filled_quantity"] == 0.5
    assert body["average_fill_price"] == 100.0
    order_request = mock_api.requests_for("POST", "/api/v3/order")[0]
    assert order_request.url.params["type"] == "MARKET"
    assert "signature" in order_request.url.params


def test_rejected_order_maps_to_422():
    seed_binance()
    response = client.post(
        "/connectors/binance/orders",
        json={
            "id": str(uuid4()),
            "signal_id": str(uuid4()),
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": 0.0001,  # notional ~0.005 << minNotional 10
            "order_type": "limit",
            "price": 50.0,
            "account_id": "default",
            "execution_mode": "paper",
        },
    )
    assert response.status_code == 422
    assert "minNotional" in response.json()["detail"]


def test_rate_limited_upstream_maps_to_429():
    mock_api = BinanceMockAPI()

    def always_limited(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"code": -1003, "msg": "slow down"})

    mock_api.routes[("GET", "/api/v3/klines")] = always_limited
    seed_binance(mock_api)

    response = client.get(
        "/connectors/binance/historical",
        params={"symbol": "BTCUSDT", "timeframe": "1h", "limit": 1},
    )
    assert response.status_code == 429


def test_stream_status_reports_no_streams_by_default():
    seed_binance()
    response = client.get("/connectors/binance/stream/status")
    assert response.status_code == 200
    assert response.json() == {
        "broker": "binance",
        "account_id": "default",
        "connected": True,
        "streaming": False,
        "streams": [],
    }


def test_stream_status_unknown_broker_returns_404():
    assert client.get("/connectors/notabroker/stream/status").status_code == 404
