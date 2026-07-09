"""End-to-end shape of GET /portfolio/{account_id} (the payload risk-engine
consumes) and account auto-creation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

ACC = "acc-snap"


def test_fresh_account_snapshot_defaults(client):
    state = client.get(f"/portfolio/{ACC}").json()
    assert state["account"]["account_id"] == ACC
    assert state["account"]["balance"] == pytest.approx(100000.0)
    assert state["account"]["equity"] == pytest.approx(100000.0)
    assert state["account"]["margin_used"] == pytest.approx(0.0)
    assert state["account"]["free_margin"] == pytest.approx(100000.0)
    assert state["positions"] == []
    assert state["pnl_daily"] == 0.0
    assert state["pnl_weekly"] == 0.0
    assert state["pnl_monthly"] == 0.0


def test_snapshot_composes_positions_exposure_and_drawdown(client):
    client.post(
        f"/portfolio/{ACC}/executions",
        json={
            "order_id": str(uuid.uuid4()),
            "status": "filled",
            "filled_quantity": 100,
            "average_fill_price": 100,
            "broker": "sim",
            "reported_at": datetime.now(timezone.utc).isoformat(),
            "symbol": "AAPL",
            "side": "buy",
            "sector": "tech",
        },
    )
    client.post(f"/portfolio/{ACC}/mark", json={"prices": {"AAPL": 105}})

    state = client.get(f"/portfolio/{ACC}").json()
    assert state["account"]["balance"] == pytest.approx(90000.0)
    assert state["account"]["equity"] == pytest.approx(100500.0)
    assert state["account"]["margin_used"] == pytest.approx(10500.0)
    assert state["account"]["free_margin"] == pytest.approx(90000.0)
    assert state["unrealized_pnl"] == pytest.approx(500.0)
    assert state["exposure"]["per_symbol"]["AAPL"] == pytest.approx(10500.0)
    assert state["exposure"]["per_sector"]["tech"] == pytest.approx(10500.0)
    assert state["drawdown"]["peak_equity"] == pytest.approx(100500.0)
    assert state["marks"]["AAPL"] == 105

    pos = state["positions"][0]
    assert pos["symbol"] == "AAPL"
    assert pos["quantity"] == 100
    assert pos["average_price"] == 100
    assert pos["account_id"] == ACC
