"""RiskLimits CRUD (admin-only writes) and circuit-breaker admin endpoints."""

from __future__ import annotations

import pytest

from app import db as db_module
from app.limits import default_limits
from app.models import CircuitBreakerRow, RiskEvent

ACC = "acc-adm"


def test_get_limits_returns_defaults_when_unset(client):
    response = client.get(f"/risk/limits/{ACC}")
    assert response.status_code == 200
    body = response.json()
    assert body["is_default"] is True
    assert body["limits"]["max_risk_per_trade"] == pytest.approx(0.01)
    assert body["limits"]["max_daily_loss"] == pytest.approx(0.03)
    assert body["limits"]["max_correlation"] == pytest.approx(0.75)
    assert body["limits"]["max_slippage"] is None


def test_put_limits_requires_auth(client):
    body = default_limits().model_dump()
    assert client.put(f"/risk/limits/{ACC}", json=body).status_code == 401


def test_put_limits_rejects_non_admin(client, trader_headers):
    body = default_limits().model_dump()
    response = client.put(f"/risk/limits/{ACC}", json=body, headers=trader_headers)
    assert response.status_code == 403


def test_put_limits_admin_persists_and_get_reflects(client, admin_headers):
    limits = default_limits().model_copy(
        update={
            "max_risk_per_trade": 0.02,
            "min_volume": 5000.0,
            "max_slippage": 0.002,
            "circuit_breaker_thresholds": {"daily_loss_soft": 0.02},
        }
    )
    response = client.put(
        f"/risk/limits/{ACC}", json=limits.model_dump(), headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["is_default"] is False

    fetched = client.get(f"/risk/limits/{ACC}").json()
    assert fetched["is_default"] is False
    assert fetched["limits"]["max_risk_per_trade"] == pytest.approx(0.02)
    assert fetched["limits"]["min_volume"] == pytest.approx(5000.0)
    assert fetched["limits"]["max_slippage"] == pytest.approx(0.002)
    assert fetched["limits"]["circuit_breaker_thresholds"]["daily_loss_soft"] == 0.02

    with db_module.SessionLocal() as session:
        events = [r for r in session.query(RiskEvent) if r.event_type == "risk.limits_updated"]
        assert len(events) == 1


def test_updated_limits_drive_validation(client, admin_headers):
    from tests.conftest import make_signal, make_state

    tight = default_limits().model_copy(update={"max_risk_per_trade": 0.001})
    client.put(f"/risk/limits/{ACC}", json=tight.model_dump(), headers=admin_headers)

    body = {
        "signal": make_signal(suggested_size=100).model_dump(mode="json"),  # risk 0.5%
        "account_id": ACC,
        "portfolio_state": make_state(account_id=ACC).model_dump(mode="json"),
    }
    decision = client.post("/risk/validate", json=body).json()
    assert decision["approved"] is False
    assert "per_trade_risk" in decision["risk_checks_failed"]
    # 0.1% of 100k / 5 = 20 units
    assert decision["max_size_allowed"] == pytest.approx(20.0)


def test_get_circuit_breaker_defaults_to_normal(client):
    response = client.get(f"/risk/circuit-breaker/{ACC}")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "NORMAL"
    assert body["error_count"] == 0


def test_reset_requires_admin(client, trader_headers):
    assert client.post(f"/risk/circuit-breaker/{ACC}/reset").status_code == 401
    assert (
        client.post(
            f"/risk/circuit-breaker/{ACC}/reset", headers=trader_headers
        ).status_code
        == 403
    )


def test_reset_returns_breaker_to_normal_and_audits(client, admin_headers):
    with db_module.SessionLocal() as session:
        session.add(
            CircuitBreakerRow(account_id=ACC, state="HARD_HALT", reason="daily_loss", error_count=7)
        )
        session.commit()

    response = client.post(f"/risk/circuit-breaker/{ACC}/reset", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "NORMAL"
    assert body["error_count"] == 0

    with db_module.SessionLocal() as session:
        events = [
            r for r in session.query(RiskEvent) if r.event_type == "risk.circuit_breaker_reset"
        ]
        assert len(events) == 1
        assert events[0].account_id == ACC
