"""P9 — global risk guard: a breach auto-halts the whole automation."""

from __future__ import annotations

from app import controller
from app import db as db_module
from app import statemachine as sm


def _session():
    return db_module.SessionLocal()


async def test_drawdown_breach_auto_halts(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_MAX_DRAWDOWN", "0.20")
    fake_clients.portfolio.drawdown = 0.25  # over the 20% limit

    with _session() as db:
        sm.enable(db)
        result = await controller.run_cycle(db, fake_clients)
        state_after = sm.get_state(db).state

    assert result.state == sm.HALTED
    assert "auto-halt" in result.summary and "drawdown" in result.summary
    assert state_after == sm.HALTED
    # No new bots were created — the guard runs before any action.
    assert fake_clients.trading.created == []


async def test_daily_loss_breach_auto_halts(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_MAX_DRAWDOWN", "0")  # disable dd, test daily loss
    monkeypatch.setenv("AUTONOMY_MAX_DAILY_LOSS", "0.05")
    fake_clients.portfolio.equity = 100000.0
    fake_clients.portfolio.pnl_daily = -6000.0  # -6% > 5% limit

    with _session() as db:
        sm.enable(db)
        result = await controller.run_cycle(db, fake_clients)

    assert result.state == sm.HALTED
    assert "daily loss" in result.summary


async def test_within_limits_keeps_trading(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_MAX_DRAWDOWN", "0.20")
    fake_clients.portfolio.drawdown = 0.05  # well within

    with _session() as db:
        sm.enable(db)
        result = await controller.run_cycle(db, fake_clients)

    assert result.state != sm.HALTED
    assert fake_clients.trading.created == ["auto:BTCUSDT:sma_crossover"]


async def test_halted_bots_are_stopped(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_MAX_DRAWDOWN", "0.20")
    # First cycle within limits creates+starts a bot.
    with _session() as db:
        sm.enable(db)
        await controller.run_cycle(db, fake_clients)
    assert any(b["status"] == "running" for b in fake_clients.trading.bots)

    # Drawdown now breaches -> next cycle halts and stops the running bot.
    fake_clients.portfolio.drawdown = 0.30
    with _session() as db:
        result = await controller.run_cycle(db, fake_clients)

    assert result.state == sm.HALTED
    assert all(b["status"] != "running" for b in fake_clients.trading.bots)


async def test_portfolio_outage_is_fail_open(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_MAX_DRAWDOWN", "0.20")
    fake_clients.portfolio.fail = True  # cannot read risk state

    with _session() as db:
        sm.enable(db)
        result = await controller.run_cycle(db, fake_clients)

    # A transient portfolio outage does NOT halt; it is recorded and trading
    # continues (per-order risk checks still apply downstream).
    assert result.state != sm.HALTED
    assert any(e.get("stage") == "risk_guard" for e in result.errors)


async def test_guard_disabled_when_thresholds_zero(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_MAX_DRAWDOWN", "0")
    monkeypatch.setenv("AUTONOMY_MAX_DAILY_LOSS", "0")
    fake_clients.portfolio.drawdown = 0.99  # would breach if guard were on

    with _session() as db:
        sm.enable(db)
        result = await controller.run_cycle(db, fake_clients)

    assert result.state != sm.HALTED
