"""Order splitting: pure math and end-to-end through the pipeline."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.router import split_order
from trading_contracts import ExecutionReport, OrderStatus
from tests.conftest import make_execution_payload


def test_split_order_math():
    assert split_order(250, 100) == [100, 100, 50]
    assert split_order(100, 100) == [100]
    assert split_order(10, 0) == [10]  # 0 disables splitting
    assert split_order(10, -1) == [10]
    assert split_order(2.5, 1.0) == [1.0, 1.0, 0.5]
    assert split_order(0.3, 0.1) == pytest.approx([0.1, 0.1, 0.1])
    assert sum(split_order(123.45, 7)) == pytest.approx(123.45)


def test_execution_splits_into_child_orders(harness, monkeypatch):
    monkeypatch.setenv("EXECUTION_MAX_CHILD_SIZE", "100")

    response = harness.client.post(
        "/executions", json=make_execution_payload(quantity=250.0)
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # Three sequential child orders hit the transport with split quantities.
    assert [order.quantity for order, _ in harness.paper.orders] == [100, 100, 50]
    # Each child carries its own id but the parent's signal.
    child_ids = {str(order.id) for order, _ in harness.paper.orders}
    assert len(child_ids) == 3

    assert body["status"] == "filled"
    assert body["filled_quantity"] == 250.0
    assert [child["quantity"] for child in body["child_orders"]] == [100, 100, 50]
    assert [child["status"] for child in body["child_orders"]] == ["filled"] * 3
    assert len(body["reports"]) == 3
    # One portfolio forward per fill.
    assert len(harness.forwarder.calls) == 3


def test_weighted_average_fill_price_across_children(harness, monkeypatch):
    monkeypatch.setenv("EXECUTION_MAX_CHILD_SIZE", "100")
    prices = iter([100.0, 102.0, 104.0])

    def priced_fill(order, market_price):
        return ExecutionReport(
            order_id=order.id,
            status=OrderStatus.FILLED,
            filled_quantity=order.quantity,
            average_fill_price=next(prices),
            broker="fake",
            reported_at=datetime.now(timezone.utc),
            raw={},
        )

    harness.paper.behavior = priced_fill
    response = harness.client.post(
        "/executions", json=make_execution_payload(quantity=250.0)
    )
    body = response.json()

    # (100*100 + 100*102 + 50*104) / 250 = 101.6
    assert body["average_fill_price"] == pytest.approx(101.6)


def test_no_splitting_below_max_child_size(harness, monkeypatch):
    monkeypatch.setenv("EXECUTION_MAX_CHILD_SIZE", "100")

    response = harness.client.post(
        "/executions", json=make_execution_payload(quantity=99.0)
    )
    assert len(response.json()["child_orders"]) == 1
    assert len(harness.paper.orders) == 1
