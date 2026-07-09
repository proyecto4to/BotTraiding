from __future__ import annotations

from typing import Callable

import httpx
import pytest

from app.registry import registry


@pytest.fixture(autouse=True)
def _reset_registry():
    registry.reset()
    yield
    registry.reset()


def make_mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, base_url="https://mock.invalid")


def default_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path

    if path == "/ping":
        return httpx.Response(200, json={"status": "ok"})

    if path == "/orders" and request.method == "POST":
        return httpx.Response(
            200,
            json={"status": "filled", "filled_quantity": 1.0, "average_fill_price": 100.0},
        )

    if path.startswith("/orders/") and path.endswith("/cancel"):
        return httpx.Response(200, json={"status": "cancelled"})

    if path == "/positions":
        return httpx.Response(
            200,
            json={
                "positions": [
                    {
                        "symbol": "BTCUSD",
                        "quantity": 1.0,
                        "average_price": 100.0,
                        "unrealized_pnl": 5.0,
                        "account_id": "default",
                    }
                ]
            },
        )

    if path == "/account":
        return httpx.Response(
            200,
            json={
                "account_id": "default",
                "balance": 1000.0,
                "equity": 1010.0,
                "margin_used": 10.0,
                "free_margin": 990.0,
                "currency": "USD",
            },
        )

    if path == "/historical":
        return httpx.Response(
            200,
            json={
                "bars": [
                    {
                        "symbol": request.url.params.get("symbol"),
                        "timeframe": request.url.params.get("timeframe"),
                        "open": 1.0,
                        "high": 2.0,
                        "low": 0.5,
                        "close": 1.5,
                        "volume": 100.0,
                        "timestamp": "2024-01-01T00:00:00Z",
                    }
                ]
            },
        )

    if path == "/tick":
        return httpx.Response(
            200,
            json={
                "symbol": request.url.params.get("symbol"),
                "bid": 1.0,
                "ask": 1.1,
                "timestamp": "2024-01-01T00:00:00Z",
            },
        )

    return httpx.Response(404, json={"error": "not found"})
