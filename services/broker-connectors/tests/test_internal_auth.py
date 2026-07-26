"""Anything that can move money or broker state requires an authenticated caller.

These endpoints used to be completely open. Because every service published its
port, reaching broker-connectors was enough to place a real order — with no
sizing, no limits, no circuit breaker and no record of who asked for it. That is
a direct bypass of ARCHITECTURE.md principle 4 ("toda orden pasa por el Risk
Engine, sin excepciones, sin bypass").

The network perimeter (loopback-only binding) contains this, but containment is
not authorisation; these tests pin the authorisation half.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

from .conftest import service_headers

anon = TestClient(app)


def _order_payload() -> dict:
    return {
        "id": str(uuid4()),
        "signal_id": str(uuid4()),
        "symbol": "BTCUSD",
        "side": "buy",
        "quantity": 1.0,
        "order_type": "market",
        "account_id": "default",
        "execution_mode": "paper",
    }


def test_place_order_without_a_token_is_rejected():
    response = anon.post("/connectors/bybit/orders", json=_order_payload())
    assert response.status_code == 401


def test_connect_without_a_token_is_rejected():
    response = anon.post(
        "/connectors/bybit/connect",
        json={"account_id": "default", "api_key": "k", "api_secret": "s", "demo": True},
    )
    assert response.status_code == 401


def test_cancel_without_a_token_is_rejected():
    response = anon.post(
        "/connectors/bybit/orders/some-order/cancel", json={"account_id": "default"}
    )
    assert response.status_code == 401


def test_a_forged_token_is_rejected():
    """The signature is what counts — a well-formed but unsigned token is not
    enough to get past the gate."""
    response = anon.post(
        "/connectors/bybit/orders",
        json=_order_payload(),
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert response.status_code == 401


def test_service_token_gets_past_the_gate():
    """A sibling service is accepted: it reaches the handler and fails on
    business rules (not connected yet), not on auth."""
    response = anon.post(
        "/connectors/bybit/orders", json=_order_payload(), headers=service_headers()
    )
    assert response.status_code != 401
    assert response.status_code != 403
