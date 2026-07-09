"""Marks -> unrealized PnL, peak-equity drawdown, floating drawdown."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

ACC = "acc-dd"


def _buy(client, symbol, qty, price):
    return client.post(
        f"/portfolio/{ACC}/executions",
        json={
            "order_id": str(uuid.uuid4()),
            "status": "filled",
            "filled_quantity": qty,
            "average_fill_price": price,
            "broker": "sim",
            "reported_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": "buy",
        },
    )


def test_mark_updates_unrealized_and_equity(client):
    _buy(client, "AAPL", 100, 100)  # cash 90000
    state = client.post(f"/portfolio/{ACC}/mark", json={"prices": {"AAPL": 110}}).json()
    assert state["unrealized_pnl"] == pytest.approx(1000.0)
    assert state["account"]["equity"] == pytest.approx(101000.0)
    assert state["positions"][0]["unrealized_pnl"] == pytest.approx(1000.0)


def test_peak_equity_and_current_drawdown(client):
    _buy(client, "AAPL", 100, 100)
    client.post(f"/portfolio/{ACC}/mark", json={"prices": {"AAPL": 110}})  # peak 101000
    dd = client.get(f"/portfolio/{ACC}/drawdown").json()
    assert dd["peak_equity"] == pytest.approx(101000.0)
    assert dd["current_drawdown"] == pytest.approx(0.0)

    client.post(f"/portfolio/{ACC}/mark", json={"prices": {"AAPL": 90}})  # equity 99000
    dd = client.get(f"/portfolio/{ACC}/drawdown").json()
    assert dd["equity"] == pytest.approx(99000.0)
    assert dd["peak_equity"] == pytest.approx(101000.0)
    assert dd["current_drawdown"] == pytest.approx((101000 - 99000) / 101000)


def test_floating_drawdown_from_unrealized_loss(client):
    _buy(client, "AAPL", 100, 100)
    client.post(f"/portfolio/{ACC}/mark", json={"prices": {"AAPL": 90}})
    dd = client.get(f"/portfolio/{ACC}/drawdown").json()
    # unrealized = -1000, equity = 99000
    assert dd["floating_drawdown"] == pytest.approx(1000 / 99000)


def test_floating_drawdown_zero_when_in_profit(client):
    _buy(client, "AAPL", 100, 100)
    client.post(f"/portfolio/{ACC}/mark", json={"prices": {"AAPL": 120}})
    dd = client.get(f"/portfolio/{ACC}/drawdown").json()
    assert dd["floating_drawdown"] == pytest.approx(0.0)


def test_fresh_account_has_no_drawdown(client):
    dd = client.get(f"/portfolio/{ACC}/drawdown").json()
    assert dd["equity"] == pytest.approx(100000.0)
    assert dd["current_drawdown"] == pytest.approx(0.0)
    assert dd["floating_drawdown"] == pytest.approx(0.0)
