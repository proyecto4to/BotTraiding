"""Mode routing and the RiskDecision invariant (architecture 2.4 / 10)."""

from __future__ import annotations

from tests.conftest import make_execution_payload


def test_paper_order_routes_to_paper_transport(harness):
    response = harness.client.post("/executions", json=make_execution_payload(mode="paper"))
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["status"] == "filled"
    assert body["execution_mode"] == "paper"
    assert body["filled_quantity"] == 10.0
    assert body["average_fill_price"] == 100.0
    assert len(harness.paper.orders) == 1
    assert harness.live.orders == []

    # Same code path, mode is data: transport got a child Order model.
    child_order, market_price = harness.paper.orders[0]
    assert child_order.quantity == 10.0
    assert market_price == 100.0

    # Persisted and retrievable.
    fetched = harness.client.get(f"/executions/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "filled"
    assert len(fetched.json()["reports"]) == 1


def test_live_order_routes_to_live_transport(harness, admin_headers):
    response = harness.client.post(
        "/executions", json=make_execution_payload(mode="live"), headers=admin_headers
    )
    assert response.status_code == 201, response.text

    assert len(harness.live.orders) == 1
    assert harness.paper.orders == []
    assert response.json()["execution_mode"] == "live"


def test_missing_risk_decision_rejected_422(harness):
    payload = make_execution_payload()
    del payload["risk_decision"]
    response = harness.client.post("/executions", json=payload)
    assert response.status_code == 422
    assert harness.paper.orders == []  # never reached a transport


def test_unapproved_risk_decision_rejected_422(harness):
    response = harness.client.post(
        "/executions", json=make_execution_payload(approved=False)
    )
    assert response.status_code == 422
    assert "approved" in response.json()["detail"].lower()
    assert harness.paper.orders == []


def test_mismatched_risk_decision_rejected_422(harness):
    import uuid

    response = harness.client.post(
        "/executions",
        json=make_execution_payload(decision_signal_id=str(uuid.uuid4())),
    )
    assert response.status_code == 422
    assert "signal_id" in response.json()["detail"]
    assert harness.paper.orders == []


def test_rejected_fill_is_not_forwarded_but_persisted(harness):
    from datetime import datetime, timezone

    from trading_contracts import ExecutionReport, OrderStatus

    def reject(order, market_price):
        return ExecutionReport(
            order_id=order.id,
            status=OrderStatus.REJECTED,
            filled_quantity=0.0,
            average_fill_price=None,
            broker="fake",
            reported_at=datetime.now(timezone.utc),
            raw={"reason": "insufficient_balance"},
        )

    harness.paper.behavior = reject
    response = harness.client.post("/executions", json=make_execution_payload())
    body = response.json()

    assert body["status"] == "rejected"
    assert harness.forwarder.calls == []  # nothing filled, nothing forwarded
    assert len(body["reports"]) == 1  # ...but the report is persisted
    assert body["reports"][0]["raw"]["reason"] == "insufficient_balance"
