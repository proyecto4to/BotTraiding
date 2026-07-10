"""Query endpoints: GET /executions (filters), GET /executions/{id}, /modes."""

from __future__ import annotations

from datetime import datetime, timezone

from trading_contracts import ExecutionReport, OrderStatus
from tests.conftest import make_execution_payload


def test_get_unknown_execution_404(harness):
    assert harness.client.get("/executions/nope").status_code == 404


def test_list_executions_filters(harness):
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

    harness.client.post("/executions", json=make_execution_payload(account_id="a1"))
    harness.client.post("/executions", json=make_execution_payload(account_id="a1"))
    harness.client.post("/executions", json=make_execution_payload(account_id="a2"))
    harness.paper.behavior = reject
    harness.client.post("/executions", json=make_execution_payload(account_id="a1"))

    assert len(harness.client.get("/executions").json()) == 4
    assert len(harness.client.get("/executions", params={"account_id": "a1"}).json()) == 3
    assert len(harness.client.get("/executions", params={"account_id": "a2"}).json()) == 1
    assert (
        len(
            harness.client.get(
                "/executions", params={"account_id": "a1", "status": "filled"}
            ).json()
        )
        == 2
    )
    assert (
        len(harness.client.get("/executions", params={"status": "rejected"}).json()) == 1
    )


def test_modes_endpoint_defaults(harness):
    response = harness.client.get("/modes")
    assert response.status_code == 200
    body = response.json()

    assert body["default_mode"] == "paper"
    assert body["override_requires_admin"] is True
    assert body["modes"]["paper"]["available"] is True
    assert body["modes"]["live"]["available"] is True
    assert body["modes"]["paper"]["transport"] == "paper-trading"
    assert body["modes"]["live"]["transport"] == "broker-connectors"


def test_modes_live_disabled(monkeypatch):
    """Without dependency overrides, the real router respects
    EXECUTION_LIVE_ENABLED and drops the live transport."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("EXECUTION_LIVE_ENABLED", "false")
    with TestClient(app) as client:
        body = client.get("/modes").json()
    assert body["modes"]["paper"]["available"] is True
    assert body["modes"]["live"]["available"] is False


def test_live_disabled_execution_503(monkeypatch, admin_headers, _test_db):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("EXECUTION_LIVE_ENABLED", "false")
    with TestClient(app) as client:
        response = client.post(
            "/executions", json=make_execution_payload(mode="live"), headers=admin_headers
        )
    assert response.status_code == 503


def test_health_and_ready(harness):
    assert harness.client.get("/health").json()["status"] == "ok"
    assert harness.client.get("/ready").json()["status"] == "ready"
