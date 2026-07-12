"""P0 — reconciliation (broker truth vs local state) and idempotent ingest.

- build_report classifies every discrepancy and absorbs fee dust via the
  tolerance;
- POST /portfolio/{id}/reconcile is admin-gated; apply=false mutates nothing,
  apply=true aligns positions to the broker and records auditable synthetic
  executions (source="reconciliation") without touching cash;
- ingesting the same client_order_id twice is a no-op (no double-count).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app import db as db_module
from app import reconcile
from app.deps import require_admin
from app.main import app
from app.models import PortfolioExecution, PortfolioPosition
from trading_contracts import AccountState, Position
from trading_contracts.auth import TokenPayload


# --- helpers -----------------------------------------------------------------


class FakeBrokerClient:
    def __init__(self, positions, *, account=None, fail_positions=False):
        self._positions = positions
        self._account = account
        self._fail_positions = fail_positions

    async def get_positions(self, broker, account_id):
        if self._fail_positions:
            raise reconcile.BrokerClientError("broker session not connected")
        return self._positions

    async def get_account(self, broker, account_id):
        if self._account is None:
            raise reconcile.BrokerClientError("no account snapshot")
        return self._account


def _local(symbol, qty, avg=100.0):
    return PortfolioPosition(
        account_id="acct-1",
        symbol=symbol,
        quantity=qty,
        average_price=avg,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        last_price=avg,
    )


def _broker(symbol, qty, avg=100.0):
    return Position(
        symbol=symbol,
        quantity=qty,
        average_price=avg,
        unrealized_pnl=0.0,
        account_id="acct-1",
    )


def _ingest(client, symbol, side, qty, price, coid=None, account="acct-1"):
    body = {
        "order_id": str(uuid.uuid4()),
        "client_order_id": coid,
        "status": "filled",
        "filled_quantity": qty,
        "average_fill_price": price,
        "broker": "binance",
        "reported_at": datetime.now(timezone.utc).isoformat(),
        "raw": {},
        "symbol": symbol,
        "side": side,
        "commission": 0.0,
    }
    return client.post(f"/portfolio/{account}/executions", json=body)


def _admin_token(roles=("admin",)):
    payload = {
        "sub": str(uuid.uuid4()),
        "roles": list(roles),
        "type": "access",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


@pytest.fixture()
def app_client():
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def _use_broker(fake, *, as_admin=True):
    if as_admin:
        app.dependency_overrides[require_admin] = lambda: TokenPayload(
            sub="admin-1", roles=["admin"], type="access"
        )
    app.dependency_overrides[reconcile.get_broker_client] = lambda: fake


# --- build_report (pure) -----------------------------------------------------


def test_build_report_classifies_every_discrepancy():
    local = [_local("BTCUSD", 10), _local("SOLUSD", 3), _local("ADAUSD", 4)]
    broker = [_broker("BTCUSD", 10), _broker("SOLUSD", 2), _broker("ETHUSD", 5)]

    report = reconcile.build_report("acct-1", "binance", "acct-1", local, broker, 1e-8)

    assert [e.symbol for e in report.matched] == ["BTCUSD"]
    assert [e.symbol for e in report.quantity_mismatches] == ["SOLUSD"]
    assert [e.symbol for e in report.missing_at_broker] == ["ADAUSD"]
    assert [e.symbol for e in report.missing_locally] == ["ETHUSD"]
    assert report.discrepancies == 3


def test_build_report_tolerance_absorbs_fee_dust():
    local = [_local("BTCUSD", 10.0)]
    broker = [_broker("BTCUSD", 10.0 + 5e-9)]

    absorbed = reconcile.build_report("acct-1", "binance", "acct-1", local, broker, 1e-8)
    flagged = reconcile.build_report("acct-1", "binance", "acct-1", local, broker, 1e-9)

    assert absorbed.discrepancies == 0
    assert [e.symbol for e in absorbed.matched] == ["BTCUSD"]
    assert flagged.discrepancies == 1


# --- endpoint ----------------------------------------------------------------


def test_reconcile_requires_admin(app_client):
    fake = FakeBrokerClient([_broker("BTCUSD", 8)])
    app.dependency_overrides[reconcile.get_broker_client] = lambda: fake

    no_token = app_client.post("/portfolio/acct-1/reconcile", json={"broker": "binance"})
    assert no_token.status_code == 401

    non_admin = app_client.post(
        "/portfolio/acct-1/reconcile",
        json={"broker": "binance"},
        headers={"Authorization": f"Bearer {_admin_token(roles=['trader'])}"},
    )
    assert non_admin.status_code == 403


def test_reconcile_report_only_mutates_nothing(app_client):
    _ingest(app_client, "BTCUSD", "buy", 10, 100)  # local BTC = 10, cash 99000

    fake = FakeBrokerClient(
        [_broker("BTCUSD", 8), _broker("ETHUSD", 5)],
        account=AccountState(
            account_id="acct-1", balance=99000, equity=99000,
            margin_used=0, free_margin=99000, currency="USD",
        ),
    )
    _use_broker(fake)

    resp = app_client.post(
        "/portfolio/acct-1/reconcile", json={"broker": "binance", "apply": False}
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["applied"] is False
    assert report["discrepancies"] == 2
    assert report["adjustments"] == []

    # Local state untouched: BTC still 10, no ETH, no synthetic executions.
    with db_module.SessionLocal() as s:
        positions = {p.symbol: p.quantity for p in s.query(PortfolioPosition).all()}
        synthetic = (
            s.query(PortfolioExecution)
            .filter(PortfolioExecution.source == "reconciliation")
            .count()
        )
    assert positions == {"BTCUSD": 10}
    assert synthetic == 0


def test_reconcile_apply_true_aligns_state_and_audits(app_client):
    _ingest(app_client, "BTCUSD", "buy", 10, 100)  # local BTC = 10, cash 99000

    fake = FakeBrokerClient(
        [_broker("BTCUSD", 8), _broker("ETHUSD", 5, avg=50)],
        account=AccountState(
            account_id="acct-1", balance=99000, equity=99000,
            margin_used=0, free_margin=99000, currency="USD",
        ),
    )
    _use_broker(fake)

    resp = app_client.post(
        "/portfolio/acct-1/reconcile", json={"broker": "binance", "apply": True}
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["applied"] is True
    assert {a["symbol"] for a in report["adjustments"]} == {"BTCUSD", "ETHUSD"}

    # Local positions now match broker truth; cash is NOT touched by a
    # reconciliation; corrections are recorded as synthetic executions.
    snapshot = app_client.get("/portfolio/acct-1").json()
    by_symbol = {p["symbol"]: p["quantity"] for p in snapshot["positions"]}
    assert by_symbol == {"BTCUSD": 8, "ETHUSD": 5}
    assert snapshot["account"]["balance"] == 99000

    with db_module.SessionLocal() as s:
        synthetic = (
            s.query(PortfolioExecution)
            .filter(PortfolioExecution.source == "reconciliation")
            .all()
        )
    assert len(synthetic) == 2
    assert all(e.realized_pnl == 0.0 for e in synthetic)


def test_reconcile_broker_unavailable_is_502(app_client):
    fake = FakeBrokerClient([], fail_positions=True)
    _use_broker(fake)

    resp = app_client.post(
        "/portfolio/acct-1/reconcile", json={"broker": "binance", "apply": False}
    )
    assert resp.status_code == 502


# --- idempotent ingest -------------------------------------------------------


def test_duplicate_execution_ingest_is_noop(app_client):
    coid = "child-abc-0"
    first = _ingest(app_client, "BTCUSD", "buy", 10, 100, coid=coid)
    assert first.status_code == 200
    assert first.json()["duplicate"] is False

    second = _ingest(app_client, "BTCUSD", "buy", 10, 100, coid=coid)
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    # The position reflects a single fill, not two.
    snapshot = app_client.get("/portfolio/acct-1").json()
    by_symbol = {p["symbol"]: p["quantity"] for p in snapshot["positions"]}
    assert by_symbol == {"BTCUSD": 10}
