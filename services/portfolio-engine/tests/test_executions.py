"""Execution ingest -> position/cash/realized PnL accounting."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest


def _execution(symbol="AAPL", side="buy", qty=100.0, price=10.0, **overrides):
    body = {
        "order_id": str(uuid.uuid4()),
        "status": "filled",
        "filled_quantity": qty,
        "average_fill_price": price,
        "broker": "sim",
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "side": side,
        "currency": "USD",
        "commission": 0.0,
    }
    body.update(overrides)
    return body


ACC = "acc-1"


def test_buy_opens_position_and_reduces_cash(client):
    r = client.post(f"/portfolio/{ACC}/executions", json=_execution(qty=100, price=10))
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] is True
    assert body["position"]["quantity"] == 100
    assert body["position"]["average_price"] == 10
    assert body["cash"] == pytest.approx(100000 - 1000)


def test_adding_to_position_averages_price(client):
    client.post(f"/portfolio/{ACC}/executions", json=_execution(qty=100, price=10))
    r = client.post(f"/portfolio/{ACC}/executions", json=_execution(qty=100, price=12))
    pos = r.json()["position"]
    assert pos["quantity"] == 200
    assert pos["average_price"] == pytest.approx(11.0)


def test_partial_sell_realizes_pnl_and_keeps_average(client):
    client.post(f"/portfolio/{ACC}/executions", json=_execution(qty=100, price=10))
    client.post(f"/portfolio/{ACC}/executions", json=_execution(qty=100, price=12))
    r = client.post(
        f"/portfolio/{ACC}/executions", json=_execution(side="sell", qty=50, price=14)
    )
    body = r.json()
    assert body["realized_pnl_delta"] == pytest.approx(50 * (14 - 11))
    assert body["position"]["quantity"] == 150
    assert body["position"]["average_price"] == pytest.approx(11.0)

    state = client.get(f"/portfolio/{ACC}").json()
    assert state["realized_pnl"] == pytest.approx(150.0)
    assert state["pnl_daily"] == pytest.approx(150.0)


def test_flip_long_to_short_opens_remainder_at_fill_price(client):
    client.post(f"/portfolio/{ACC}/executions", json=_execution(qty=150, price=11))
    r = client.post(
        f"/portfolio/{ACC}/executions", json=_execution(side="sell", qty=300, price=14)
    )
    body = r.json()
    assert body["realized_pnl_delta"] == pytest.approx(150 * (14 - 11))
    assert body["position"]["quantity"] == -150
    assert body["position"]["average_price"] == pytest.approx(14.0)


def test_short_cover_realizes_pnl(client):
    client.post(f"/portfolio/{ACC}/executions", json=_execution(side="sell", qty=100, price=50))
    r = client.post(
        f"/portfolio/{ACC}/executions", json=_execution(side="buy", qty=100, price=45)
    )
    body = r.json()
    assert body["realized_pnl_delta"] == pytest.approx(100 * (50 - 45))
    assert body["position"]["quantity"] == 0


def test_commission_reduces_cash(client):
    r = client.post(
        f"/portfolio/{ACC}/executions", json=_execution(qty=10, price=100, commission=5.0)
    )
    assert r.json()["cash"] == pytest.approx(100000 - 1000 - 5)


def test_non_fill_status_does_not_touch_state(client):
    r = client.post(
        f"/portfolio/{ACC}/executions",
        json=_execution(status="rejected", qty=0, price=None),
    )
    body = r.json()
    assert body["applied"] is False
    assert body["cash"] == pytest.approx(100000)
    state = client.get(f"/portfolio/{ACC}").json()
    assert state["positions"] == []


def test_closed_position_disappears_from_snapshot(client):
    client.post(f"/portfolio/{ACC}/executions", json=_execution(qty=10, price=10))
    client.post(f"/portfolio/{ACC}/executions", json=_execution(side="sell", qty=10, price=12))
    state = client.get(f"/portfolio/{ACC}").json()
    assert state["positions"] == []
    assert state["realized_pnl"] == pytest.approx(20.0)
