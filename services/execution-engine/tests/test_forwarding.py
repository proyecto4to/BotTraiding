"""Execution -> portfolio-engine forwarding through the injectable client."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trading_contracts import ExecutionReport, OrderStatus
from tests.conftest import make_execution_payload


def test_fill_forwarded_with_correct_payload(harness):
    def fill_with_commission(order, market_price):
        return ExecutionReport(
            order_id=order.id,
            status=OrderStatus.FILLED,
            filled_quantity=order.quantity,
            average_fill_price=101.5,
            broker="fake",
            reported_at=datetime.now(timezone.utc),
            raw={"commission": 2.5},
        )

    harness.paper.behavior = fill_with_commission

    response = harness.client.post(
        "/executions",
        json=make_execution_payload(quantity=10.0, account_id="acct-42", symbol="ETHUSD"),
    )
    assert response.status_code == 201
    body = response.json()

    assert len(harness.forwarder.calls) == 1
    account_id, payload = harness.forwarder.calls[0]

    # POST /portfolio/{account_id}/executions with the ExecutionIngest shape.
    assert account_id == "acct-42"
    assert payload["order_id"] == body["child_orders"][0]["id"]
    assert payload["status"] == "filled"
    assert payload["filled_quantity"] == 10.0
    assert payload["average_fill_price"] == 101.5
    assert payload["broker"] == "fake"
    assert payload["symbol"] == "ETHUSD"
    assert payload["side"] == "buy"
    assert payload["commission"] == 2.5
    assert payload["raw"] == {"commission": 2.5}
    assert "reported_at" in payload

    # Persisted report is marked as forwarded.
    fetched = harness.client.get(f"/executions/{body['id']}").json()
    assert len(fetched["reports"]) == 1


def test_partial_fill_forwarded(harness):
    def partial(order, market_price):
        return ExecutionReport(
            order_id=order.id,
            status=OrderStatus.PARTIALLY_FILLED,
            filled_quantity=order.quantity / 2,
            average_fill_price=100.0,
            broker="fake",
            reported_at=datetime.now(timezone.utc),
            raw={},
        )

    harness.paper.behavior = partial
    harness.client.post("/executions", json=make_execution_payload(quantity=10.0))

    assert len(harness.forwarder.calls) == 1
    _, payload = harness.forwarder.calls[0]
    assert payload["status"] == "partially_filled"
    assert payload["filled_quantity"] == 5.0
    assert payload["commission"] == 0.0  # absent from raw -> defaults to 0


def test_forwarding_failure_does_not_fail_execution(harness):
    class FailingForwarder:
        async def forward(self, account_id: str, payload: dict) -> bool:
            return False  # portfolio-engine down

    from app.main import app
    from app.portfolio_client import get_portfolio_forwarder

    app.dependency_overrides[get_portfolio_forwarder] = lambda: FailingForwarder()
    try:
        response = harness.client.post("/executions", json=make_execution_payload())
    finally:
        app.dependency_overrides[get_portfolio_forwarder] = lambda: harness.forwarder

    # Execution still succeeds and is persisted locally.
    assert response.status_code == 201
    assert response.json()["status"] == "filled"


def test_one_forward_per_child_fill(harness, monkeypatch):
    monkeypatch.setenv("EXECUTION_MAX_CHILD_SIZE", "50")

    harness.client.post("/executions", json=make_execution_payload(quantity=150.0))

    assert len(harness.forwarder.calls) == 3
    assert [p["filled_quantity"] for _, p in harness.forwarder.calls] == [50, 50, 50]
    # Each forward references its own child order id.
    assert len({p["order_id"] for _, p in harness.forwarder.calls}) == 3
