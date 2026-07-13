"""POST /risk/validate end-to-end with inline portfolio state: approved and
rejected paths, circuit-breaker semantics, portfolio-engine client injection
and risk_events audit persistence."""

from __future__ import annotations

import pytest

from app import db as db_module
from app.models import CircuitBreakerRow, RiskEvent
from app.portfolio_client import PortfolioUnavailableError, get_portfolio_client
from tests.conftest import make_signal, make_state
from trading_contracts import Position

ACC = "acc-1"


def _payload(signal=None, state=None, account_id=ACC, risk_override=None):
    body = {
        "signal": (signal or make_signal()).model_dump(mode="json"),
        "account_id": account_id,
    }
    if state is not None:
        body["portfolio_state"] = state.model_dump(mode="json")
    if risk_override is not None:
        body["risk_per_trade_override"] = risk_override
    return body


def _events(event_type=None):
    with db_module.SessionLocal() as session:
        rows = session.query(RiskEvent).all()
        if event_type:
            rows = [r for r in rows if r.event_type == event_type]
        return rows


def _set_breaker(state_value: str):
    with db_module.SessionLocal() as session:
        session.add(CircuitBreakerRow(account_id=ACC, state=state_value, reason="preset"))
        session.commit()


def test_validate_approved_path(client):
    signal = make_signal(suggested_size=100, price=100, stop_loss=95)
    response = client.post("/risk/validate", json=_payload(signal, make_state()))
    assert response.status_code == 200
    decision = response.json()

    assert decision["approved"] is True
    assert decision["reason"] == "approved"
    assert decision["signal_id"] == str(signal.id)
    assert decision["risk_checks_failed"] == []
    assert len(decision["risk_checks_passed"]) == 15
    assert decision["circuit_breaker_state"] == "NORMAL"
    assert decision["positions_should_close"] is False
    # sizing: 1% of 100k / stop distance 5 = 200
    assert decision["max_size_allowed"] == pytest.approx(200.0)
    assert decision["adjusted_stop"] == pytest.approx(95.0)
    assert decision["sizing"]["size_by_risk"] == pytest.approx(200.0)
    assert _events("risk.rejected") == []


def test_risk_override_reduces_size(client):
    # Account risk 1% -> size 200. Bot allocated 0.5% -> size halves to 100.
    signal = make_signal(suggested_size=100, price=100, stop_loss=95)
    response = client.post(
        "/risk/validate", json=_payload(signal, make_state(), risk_override=0.005)
    )
    decision = response.json()
    assert decision["approved"] is True
    assert decision["max_size_allowed"] == pytest.approx(100.0)


def test_risk_override_cannot_exceed_account_cap(client):
    # An override above the account max (1%) is capped, not honored.
    signal = make_signal(suggested_size=100, price=100, stop_loss=95)
    response = client.post(
        "/risk/validate", json=_payload(signal, make_state(), risk_override=0.05)
    )
    decision = response.json()
    assert decision["max_size_allowed"] == pytest.approx(200.0)


def test_validate_rejects_over_daily_loss(client):
    # Raise the breaker thresholds so the plain daily_loss check (not the
    # circuit breaker, which sits above the limit by default) rejects.
    from app import limits as limits_repo
    from app.limits import default_limits

    with db_module.SessionLocal() as session:
        limits_repo.save_limits(
            session,
            ACC,
            default_limits().model_copy(
                update={
                    "circuit_breaker_thresholds": {
                        "daily_loss_soft": 0.5,
                        "daily_loss_hard": 0.75,
                    }
                }
            ),
        )
        session.commit()

    state = make_state(pnl_daily=-5000)  # 5% > 3% limit
    response = client.post("/risk/validate", json=_payload(state=state))
    decision = response.json()

    assert decision["approved"] is False
    assert "daily_loss" in decision["risk_checks_failed"]
    assert "daily_loss" in decision["reason"]
    # machine-readable reasons + audit row persisted
    rejected = _events("risk.rejected")
    assert len(rejected) == 1
    assert rejected[0].signal_id == decision["signal_id"]
    assert rejected[0].payload["approved"] is False


def test_validate_rejects_oversized_trade_but_reports_max_size(client):
    signal = make_signal(suggested_size=300, price=100, stop_loss=95)  # risk 1500 > 1000
    response = client.post("/risk/validate", json=_payload(signal, make_state()))
    decision = response.json()
    assert decision["approved"] is False
    assert "per_trade_risk" in decision["risk_checks_failed"]
    assert decision["max_size_allowed"] == pytest.approx(200.0)


def test_hard_halt_rejects_everything_and_flags_close(client):
    _set_breaker("HARD_HALT")
    response = client.post("/risk/validate", json=_payload(state=make_state()))
    decision = response.json()
    assert decision["approved"] is False
    assert decision["positions_should_close"] is True
    assert decision["circuit_breaker_state"] == "HARD_HALT"
    assert "circuit_breaker" in decision["risk_checks_failed"]
    assert len(_events("risk.rejected")) == 1


def test_soft_halt_rejects_new_positions(client):
    _set_breaker("SOFT_HALT")
    response = client.post("/risk/validate", json=_payload(state=make_state()))
    decision = response.json()
    assert decision["approved"] is False
    assert decision["positions_should_close"] is False
    assert "circuit_breaker" in decision["risk_checks_failed"]


def test_soft_halt_allows_reducing_positions(client):
    _set_breaker("SOFT_HALT")
    state = make_state(
        positions=[
            Position(symbol="AAPL", quantity=100, average_price=100, account_id=ACC)
        ],
        per_symbol={"AAPL": 10000.0},
        gross_exposure=10000.0,
    )
    signal = make_signal(side="sell", suggested_size=50, stop_loss=105)
    decision = client.post("/risk/validate", json=_payload(signal, state)).json()
    assert decision["approved"] is True
    assert decision["circuit_breaker_state"] == "SOFT_HALT"


def test_validate_escalates_breaker_from_state(client):
    # daily loss 4% -> above soft (3%), below hard (4.5%)
    state = make_state(pnl_daily=-4000)
    decision = client.post("/risk/validate", json=_payload(state=state)).json()
    assert decision["circuit_breaker_state"] == "SOFT_HALT"
    assert decision["approved"] is False
    assert len(_events("risk.circuit_breaker")) == 1

    status = client.get(f"/risk/circuit-breaker/{ACC}").json()
    assert status["state"] == "SOFT_HALT"


class _FakeClient:
    def __init__(self, state=None, error=None):
        self.state = state
        self.error = error
        self.calls = 0

    async def get_state(self, account_id):
        self.calls += 1
        if self.error:
            raise self.error
        return self.state


def test_validate_fetches_state_via_injected_client(client):
    from app.main import app

    fake = _FakeClient(state=make_state())
    app.dependency_overrides[get_portfolio_client] = lambda: fake
    try:
        decision = client.post("/risk/validate", json=_payload()).json()
        assert fake.calls == 1
        assert decision["approved"] is True
    finally:
        app.dependency_overrides.pop(get_portfolio_client, None)


def test_validate_rejects_when_portfolio_engine_unavailable(client):
    from app.main import app

    fake = _FakeClient(error=PortfolioUnavailableError("connection refused"))
    app.dependency_overrides[get_portfolio_client] = lambda: fake
    try:
        decision = client.post("/risk/validate", json=_payload()).json()
        assert decision["approved"] is False
        assert "portfolio_state_unavailable" in decision["reason"]
        assert decision["risk_checks_failed"] == ["portfolio_state"]
        assert len(_events("risk.rejected")) == 1
        # the failure counted against the breaker error window
        status = client.get(f"/risk/circuit-breaker/{ACC}").json()
        assert status["error_count"] == 1
    finally:
        app.dependency_overrides.pop(get_portfolio_client, None)
