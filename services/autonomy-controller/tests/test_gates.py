"""P18 — paper -> live promotion gates and the promote-live flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import controller
from app import db as db_module
from app import gates
from app import statemachine as sm
from app.models import AutonomyDecisionRow


def _session():
    return db_module.SessionLocal()


# --- pure gate logic ---------------------------------------------------------


def test_all_gates_pass():
    snap = gates.PromotionSnapshot(paper_days=20, drawdown=0.05, total_return=0.08)
    report = gates.evaluate_gates(snap, min_days=14, max_dd=0.20, min_return=0.0)
    assert report.ready is True
    assert all(g.passed for g in report.gates)


def test_gate_fails_on_short_track_record():
    snap = gates.PromotionSnapshot(paper_days=3, drawdown=0.05, total_return=0.08)
    report = gates.evaluate_gates(snap, min_days=14, max_dd=0.20, min_return=0.0)
    assert report.ready is False
    assert any(g.name == "min_paper_days" and not g.passed for g in report.gates)


def test_gate_fails_on_drawdown_and_return():
    snap = gates.PromotionSnapshot(paper_days=30, drawdown=0.35, total_return=-0.02)
    report = gates.evaluate_gates(snap, min_days=14, max_dd=0.20, min_return=0.0)
    assert report.ready is False
    failing = {g.name for g in report.gates if not g.passed}
    assert {"max_drawdown", "min_return"} <= failing


def test_optional_sharpe_gate_blocks_when_unavailable():
    snap = gates.PromotionSnapshot(paper_days=30, drawdown=0.05, total_return=0.1, sharpe=None)
    report = gates.evaluate_gates(snap, min_days=14, max_dd=0.2, min_return=0.0, min_sharpe=1.0)
    assert report.ready is False
    assert any(g.name == "min_sharpe" and not g.passed for g in report.gates)


def test_backtest_coherence_gate():
    ok = gates.PromotionSnapshot(
        paper_days=30, drawdown=0.05, total_return=0.10, paper_return=0.10, backtest_return=0.11
    )
    report = gates.evaluate_gates(ok, min_days=14, max_dd=0.2, min_return=0.0, coherence_tol=0.2)
    assert report.ready is True

    off = gates.PromotionSnapshot(
        paper_days=30, drawdown=0.05, total_return=0.02, paper_return=0.02, backtest_return=0.20
    )
    report = gates.evaluate_gates(off, min_days=14, max_dd=0.2, min_return=0.0, coherence_tol=0.2)
    assert any(g.name == "backtest_coherence" and not g.passed for g in report.gates)


# --- readiness assembly ------------------------------------------------------


async def test_build_readiness_computes_return(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_MIN_PAPER_DAYS", "0")
    fake_clients.portfolio.drawdown = 0.05
    fake_clients.portfolio.equity = 108000
    fake_clients.portfolio.realized = 8000  # 8% on a 100k base
    with _session() as db:
        report = await controller.build_readiness(db, fake_clients)
    assert report.ready is True


async def test_build_readiness_blocks_on_portfolio_outage(fake_clients):
    fake_clients.portfolio.fail = True
    with _session() as db:
        report = await controller.build_readiness(db, fake_clients)
    assert report.ready is False
    assert any(g.name == "portfolio_available" for g in report.gates)


# --- promote-live endpoint ---------------------------------------------------


def test_promote_live_requires_admin(client, trader_headers):
    assert client.post("/autonomy/promote-live").status_code == 401
    assert client.post("/autonomy/promote-live", headers=trader_headers).status_code == 403


def test_promote_live_blocked_when_gates_fail(client, admin_headers):
    with _session() as db:
        sm.enable(db)
        sm.promote_to_paper(db)  # TRADING_PAPER but 0 days of record
    resp = client.post("/autonomy/promote-live", headers=admin_headers)
    assert resp.status_code == 409
    assert "gates not met" in resp.json()["detail"]


def test_promote_live_succeeds_when_gates_pass(client, admin_headers, fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_MIN_PAPER_DAYS", "0")
    fake_clients.portfolio.drawdown = 0.03
    with _session() as db:
        sm.enable(db)
        sm.promote_to_paper(db)
    resp = client.post("/autonomy/promote-live", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["state"] == "TRADING_LIVE"


def test_promote_live_only_from_paper(client, admin_headers, monkeypatch):
    monkeypatch.setenv("AUTONOMY_MIN_PAPER_DAYS", "0")
    # From LEARNING (not paper) -> gates may pass but the transition is invalid.
    with _session() as db:
        sm.enable(db)  # LEARNING
    resp = client.post("/autonomy/promote-live", headers=admin_headers)
    assert resp.status_code == 409


def test_readiness_endpoint(client, admin_headers):
    resp = client.get("/autonomy/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert "ready" in body and "gates" in body and "state" in body


# --- live bots ---------------------------------------------------------------


async def test_live_state_creates_live_bots(fake_clients):
    with _session() as db:
        sm.enable(db)
        sm.promote_to_paper(db)
        sm.promote_to_live(db)
        await controller.run_cycle(db, fake_clients)
    assert fake_clients.trading.specs[0]["execution_mode"] == "live"
