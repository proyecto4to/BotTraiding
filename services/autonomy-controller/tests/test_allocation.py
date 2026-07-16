"""P7 — capital allocation: AI weights -> per-strategy budget + rebalance."""

from __future__ import annotations

from app import allocation, controller
from app import db as db_module
from app import statemachine as sm


def _session():
    return db_module.SessionLocal()


# --- allocation math (pure) --------------------------------------------------


def test_allocation_splits_by_weight():
    selection = [
        {"symbol": "BTCUSDT", "strategy_key": "a", "weight": 0.6},
        {"symbol": "ETHUSDT", "strategy_key": "b", "weight": 0.4},
    ]
    plan = allocation.build_allocation_plan(
        selection, deployable=1.0, base_risk=0.01, max_per_symbol=1.0
    )
    a, b = plan
    assert a["share"] == 0.6 and b["share"] == 0.4
    assert a["capital_fraction"] == 0.6 and b["capital_fraction"] == 0.4
    # per-trade risk sums to the base budget.
    assert round(a["risk_per_trade"] + b["risk_per_trade"], 6) == 0.01
    # totals never exceed the budget.
    assert sum(x["capital_fraction"] for x in plan) <= 1.0


def test_allocation_equal_split_when_no_weights():
    selection = [
        {"symbol": "BTCUSDT", "strategy_key": "a", "weight": 0.0},
        {"symbol": "ETHUSDT", "strategy_key": "b", "weight": 0.0},
    ]
    plan = allocation.build_allocation_plan(selection, deployable=1.0, base_risk=0.01)
    assert plan[0]["share"] == 0.5 and plan[1]["share"] == 0.5


def test_allocation_caps_per_symbol():
    selection = [
        {"symbol": "BTCUSDT", "strategy_key": "a", "weight": 0.9},
        {"symbol": "ETHUSDT", "strategy_key": "b", "weight": 0.1},
    ]
    plan = allocation.build_allocation_plan(
        selection, deployable=1.0, base_risk=0.01, max_per_symbol=0.5
    )
    # The dominant strategy is capped at 50% even though its share is 90%.
    assert plan[0]["capital_fraction"] == 0.5
    assert sum(x["capital_fraction"] for x in plan) <= 1.0


def test_allocation_changed_threshold():
    same = {"risk_per_trade": 0.006}
    drifted = {"risk_per_trade": 0.009}
    assert allocation.allocation_changed(same, {"risk_per_trade": 0.006}, threshold=0.1) is False
    assert allocation.allocation_changed(same, drifted, threshold=0.1) is True
    assert allocation.allocation_changed(None, {"risk_per_trade": 0.004}) is True


# --- controller integration --------------------------------------------------


async def test_created_bot_carries_allocation(fake_clients):
    with _session() as db:
        sm.enable(db)
        await controller.run_cycle(db, fake_clients)

    spec = fake_clients.trading.specs[0]
    assert "risk_allocation" in spec
    assert spec["risk_allocation"]["risk_per_trade"] > 0
    # Single strategy at weight 1.0 gets the full base risk budget.
    assert spec["risk_allocation"]["capital_fraction"] <= 1.0


async def test_weight_shift_rebalances_bot(fake_clients):
    # First cycle: two strategies -> two bots with their allocations.
    fake_clients.ai.ranked_value = [
        {"key": "sma_crossover", "category": "trend", "weight": 0.5},
        {"key": "rsi2_reversion", "category": "mean_reversion", "weight": 0.5},
    ]
    import os

    os.environ["AUTONOMY_TOP_N"] = "2"
    try:
        with _session() as db:
            sm.enable(db)
            await controller.run_cycle(db, fake_clients)
        assert len(fake_clients.trading.created) == 2
        assert fake_clients.trading.updated == []

        # Weights shift materially -> next cycle rebalances (stop+patch+start).
        fake_clients.ai.ranked_value = [
            {"key": "sma_crossover", "category": "trend", "weight": 0.9},
            {"key": "rsi2_reversion", "category": "mean_reversion", "weight": 0.1},
        ]
        with _session() as db:
            result = await controller.run_cycle(db, fake_clients)
    finally:
        os.environ.pop("AUTONOMY_TOP_N", None)

    assert len(fake_clients.trading.updated) >= 1
    assert any(a["action"] == "rebalance" for a in result.actions)


async def test_stable_weights_do_not_rebalance(fake_clients):
    with _session() as db:
        sm.enable(db)
        await controller.run_cycle(db, fake_clients)
    with _session() as db:
        result = await controller.run_cycle(db, fake_clients)

    # Same weights -> no rebalance, no churn.
    assert fake_clients.trading.updated == []
    assert result.actions == []
