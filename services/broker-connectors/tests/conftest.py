from __future__ import annotations

import os
from typing import Callable

import httpx
import pytest

# The suite must always exercise the in-memory registry deterministically;
# per-test Redis registries are built explicitly in test_session_store.py.
os.environ.pop("REDIS_URL", None)
os.environ.pop("SESSION_STORE", None)
# Signing key for the service tokens the order endpoints now require.
os.environ.setdefault("JWT_SECRET", "test-secret")

from app.registry import registry  # noqa: E402 - env scrub must run first
from trading_contracts.auth import service_auth_header  # noqa: E402


def service_headers(name: str = "execution-engine") -> dict[str, str]:
    """Authorization header for a sibling service, the way execution-engine and
    market-data call this one. Connect/place/cancel reject unauthenticated
    callers, so API tests speak as a real internal caller."""
    return service_auth_header(name)


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
