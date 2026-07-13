"""The tick: selection -> bot actions, gates, promotion, degradation."""

from __future__ import annotations

import pytest

from app import controller
from app import db as db_module
from app import statemachine as sm


def _session():
    return db_module.SessionLocal()


async def test_off_state_skips(fake_clients):
    with _session() as db:
        result = await controller.run_cycle(db, fake_clients)
    assert result.acted is False
    assert "skipped" in result.summary
    # No downstream calls when off.
    assert fake_clients.market_data.calls == []


async def test_halted_state_skips(fake_clients):
    with _session() as db:
        sm.enable(db)
        sm.halt(db, reason="x")
        result = await controller.run_cycle(db, fake_clients)
    assert result.acted is False
    assert fake_clients.trading.created == []


async def test_learning_selects_creates_bot_and_promotes(fake_clients):
    with _session() as db:
        sm.enable(db)  # LEARNING
        result = await controller.run_cycle(db, fake_clients)
        state_after = sm.get_state(db).state

    # One strategy selected -> one bot created and started.
    assert result.acted is True
    assert fake_clients.trading.created == ["auto:BTCUSDT:sma_crossover"]
    assert len(fake_clients.trading.started) == 1
    # First usable selection promotes LEARNING -> TRADING_PAPER.
    assert state_after == sm.TRADING_PAPER
    assert result.state == sm.TRADING_PAPER


async def test_idempotent_second_cycle_creates_no_duplicate(fake_clients):
    with _session() as db:
        sm.enable(db)
        await controller.run_cycle(db, fake_clients)
    with _session() as db:
        result = await controller.run_cycle(db, fake_clients)

    # Bot already exists and is running -> no new create, no new start.
    assert fake_clients.trading.created == ["auto:BTCUSDT:sma_crossover"]
    assert len(fake_clients.trading.started) == 1
    assert result.actions == []


async def test_deselected_bot_is_stopped(fake_clients):
    with _session() as db:
        sm.enable(db)
        await controller.run_cycle(db, fake_clients)  # creates sma_crossover bot
    # Regime shifts: the AI now prefers a different strategy.
    fake_clients.ai.ranked_value = [
        {"key": "rsi2_reversion", "category": "mean_reversion", "weight": 1.0}
    ]
    with _session() as db:
        result = await controller.run_cycle(db, fake_clients)

    assert "auto:BTCUSDT:rsi2_reversion" in fake_clients.trading.created
    assert any(a["action"] == "stop" for a in result.actions)


async def test_market_data_failure_is_isolated(fake_clients):
    fake_clients.market_data.fail = True
    with _session() as db:
        sm.enable(db)
        result = await controller.run_cycle(db, fake_clients)
    # No selection, no bot, but the cycle recorded the error and did not crash.
    assert fake_clients.trading.created == []
    assert result.errors and result.errors[0]["symbol"] == "BTCUSDT"


async def test_trading_engine_list_failure_recorded(fake_clients):
    fake_clients.trading.fail_list = True
    with _session() as db:
        sm.enable(db)
        result = await controller.run_cycle(db, fake_clients)
    assert any(e.get("stage") == "list_bots" for e in result.errors)


async def test_decision_is_persisted(fake_clients):
    with _session() as db:
        sm.enable(db)
        await controller.run_cycle(db, fake_clients)
        rows = controller.recent_decisions(db, 10)
    assert len(rows) == 1
    assert rows[0].selection[0]["strategy_key"] == "sma_crossover"
