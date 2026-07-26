"""P18 — paper -> live promotion gates and the promote-live flow."""

from __future__ import annotations

from app import controller, gates
from app import db as db_module
from app import statemachine as sm


def _session():
    return db_module.SessionLocal()


# --- pure gate logic ---------------------------------------------------------


def _passing_snapshot(**overrides) -> gates.PromotionSnapshot:
    """A track record that clears every gate, including the ones that are on by
    default (Sharpe, backtest coherence, closed trades). Override one field to
    test that one gate."""
    base = dict(
        paper_days=20,
        drawdown=0.05,
        total_return=0.08,
        closed_trades=100,
        sharpe=1.2,
        paper_return=0.08,
        backtest_return=0.09,
    )
    base.update(overrides)
    return gates.PromotionSnapshot(**base)


def test_all_gates_pass():
    report = gates.evaluate_gates(_passing_snapshot())
    assert report.ready is True
    assert all(g.passed for g in report.gates)


def test_gate_fails_on_short_track_record():
    report = gates.evaluate_gates(_passing_snapshot(paper_days=3))
    assert report.ready is False
    assert any(g.name == "min_paper_days" and not g.passed for g in report.gates)


def test_gate_fails_on_drawdown_and_return():
    report = gates.evaluate_gates(_passing_snapshot(drawdown=0.35, total_return=-0.02))
    assert report.ready is False
    failing = {g.name for g in report.gates if not g.passed}
    assert {"max_drawdown", "min_return"} <= failing


def test_breaking_even_is_not_good_enough():
    """Zero return proves only that the system avoided losing. Promoting on that
    was the old default; it must now fail."""
    report = gates.evaluate_gates(_passing_snapshot(total_return=0.0))
    assert report.ready is False
    assert any(g.name == "min_return" and not g.passed for g in report.gates)


def test_thin_track_record_is_rejected():
    """14 days and three lucky fills must not read like a real track record."""
    report = gates.evaluate_gates(_passing_snapshot(closed_trades=3))
    assert report.ready is False
    assert any(g.name == "min_closed_trades" and not g.passed for g in report.gates)


def test_closed_trades_gate_can_be_disabled():
    report = gates.evaluate_gates(_passing_snapshot(closed_trades=0), min_trades=0)
    assert report.ready is True
    assert not any(g.name == "min_closed_trades" for g in report.gates)


def test_sharpe_gate_is_on_by_default_and_blocks_when_unavailable():
    report = gates.evaluate_gates(_passing_snapshot(sharpe=None))
    assert report.ready is False
    assert any(g.name == "min_sharpe" and not g.passed for g in report.gates)


def test_coherence_gate_is_off_by_default():
    """Deliberately off: no backtest baseline is wired into build_readiness yet,
    so enabling it would block promotion forever rather than make it stricter.
    Documented in config.backtest_coherence_tolerance."""
    report = gates.evaluate_gates(_passing_snapshot(backtest_return=None))
    assert report.ready is True
    assert not any(g.name == "backtest_coherence" for g in report.gates)


def test_coherence_gate_blocks_when_enabled_without_a_baseline():
    report = gates.evaluate_gates(_passing_snapshot(backtest_return=None), coherence_tol=0.3)
    assert report.ready is False
    assert any(g.name == "backtest_coherence" and not g.passed for g in report.gates)


def test_backtest_coherence_gate():
    report = gates.evaluate_gates(
        _passing_snapshot(paper_return=0.10, backtest_return=0.11), coherence_tol=0.2
    )
    assert report.ready is True

    off = _passing_snapshot(total_return=0.02, paper_return=0.02, backtest_return=0.20)
    report = gates.evaluate_gates(off, coherence_tol=0.2)
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
    # A track record that actually earns the promotion: 8% on a 100k base.
    fake_clients.portfolio.equity = 108000
    fake_clients.portfolio.realized = 8000
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
