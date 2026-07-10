"""Cancel: remaining children cancelled, cancel propagated to the transport."""

from __future__ import annotations

from datetime import datetime, timezone

from app.retry import TransientTransportError
from trading_contracts import ExecutionReport, OrderStatus
from tests.conftest import make_execution_payload


def submitted_report(order, market_price):
    """A working order resting at the venue (non-terminal)."""
    return ExecutionReport(
        order_id=order.id,
        status=OrderStatus.SUBMITTED,
        filled_quantity=0.0,
        average_fill_price=None,
        broker="fake",
        reported_at=datetime.now(timezone.utc),
        raw={},
    )


def test_cancel_propagates_to_transport(harness):
    harness.paper.behavior = submitted_report

    created = harness.client.post("/executions", json=make_execution_payload())
    body = created.json()
    assert body["status"] == "submitted"
    child_id = body["child_orders"][0]["id"]

    cancelled = harness.client.post(f"/executions/{body['id']}/cancel")
    assert cancelled.status_code == 200
    result = cancelled.json()

    assert result["status"] == "cancelled"
    assert result["cancelled_children"] == 1
    assert result["transport_cancelled"] == 1
    assert harness.paper.cancels == [child_id]  # cancel reached the venue

    fetched = harness.client.get(f"/executions/{body['id']}").json()
    assert fetched["status"] == "cancelled"
    assert fetched["child_orders"][0]["status"] == "cancelled"


def test_cancel_pending_children_after_error_without_transport(harness, monkeypatch):
    monkeypatch.setenv("EXECUTION_MAX_CHILD_SIZE", "100")
    harness.paper.behavior = lambda order, market_price: TransientTransportError("down")

    created = harness.client.post(
        "/executions", json=make_execution_payload(quantity=250.0)
    )
    body = created.json()
    assert body["status"] == "error"  # child 1 errored, 2 & 3 still pending

    cancelled = harness.client.post(f"/executions/{body['id']}/cancel")
    result = cancelled.json()

    assert result["cancelled_children"] == 2  # the two pending children
    assert result["transport_cancelled"] == 0  # they were never at the venue
    assert harness.paper.cancels == []

    fetched = harness.client.get(f"/executions/{body['id']}").json()
    assert [child["status"] for child in fetched["child_orders"]] == [
        "error",
        "cancelled",
        "cancelled",
    ]


def test_cancel_filled_execution_conflict(harness):
    created = harness.client.post("/executions", json=make_execution_payload())
    execution_id = created.json()["id"]

    response = harness.client.post(f"/executions/{execution_id}/cancel")
    assert response.status_code == 409


def test_cancel_twice_conflict(harness):
    harness.paper.behavior = submitted_report
    created = harness.client.post("/executions", json=make_execution_payload())
    execution_id = created.json()["id"]

    assert harness.client.post(f"/executions/{execution_id}/cancel").status_code == 200
    assert harness.client.post(f"/executions/{execution_id}/cancel").status_code == 409


def test_cancel_unknown_execution_404(harness):
    assert harness.client.post("/executions/nope/cancel").status_code == 404
