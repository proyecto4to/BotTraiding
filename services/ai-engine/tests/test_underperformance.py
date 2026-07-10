"""Underperformance rules -> disable recommendations (advisory only)."""

from __future__ import annotations

import pytest

from app.underperformance import (
    Recommendation,
    RuleConfig,
    evaluate_strategy,
    max_drawdown_from_returns,
    rolling_sharpe,
)

CFG = RuleConfig(min_trades=10, sharpe_threshold=0.0, max_drawdown=0.20)


def test_rolling_sharpe_sign() -> None:
    assert rolling_sharpe([0.01, 0.02, 0.015, 0.03]) > 0
    assert rolling_sharpe([-0.01, -0.02, -0.015, -0.03]) < 0


def test_max_drawdown_from_returns() -> None:
    # +10% then -50%: dd = 1 - 0.55/1.1 = 0.5
    dd = max_drawdown_from_returns([0.10, -0.50])
    assert dd == pytest.approx(0.5)
    assert max_drawdown_from_returns([0.01, 0.02]) == pytest.approx(0.0)


def test_negative_sharpe_triggers_disable_recommendation() -> None:
    losing = [-0.01, 0.002, -0.012, 0.001, -0.011] * 4  # 20 trades, mean < 0
    recs = evaluate_strategy("loser", losing, CFG)
    rules = {r.rule for r in recs}
    assert "rolling_sharpe_below_threshold" in rules
    rec = next(r for r in recs if r.rule == "rolling_sharpe_below_threshold")
    assert rec.action == "disable"
    assert rec.strategy_key == "loser"
    assert rec.metrics["rolling_sharpe"] < 0.0


def test_profitable_strategy_gets_no_recommendation() -> None:
    winning = [0.01, -0.004, 0.012, -0.003, 0.011] * 4
    assert evaluate_strategy("winner", winning, CFG) == []


def test_sharpe_rule_needs_min_trades() -> None:
    few_losses = [-0.05] * 5  # clearly bad but below min_trades=10
    recs = evaluate_strategy("young", few_losses, CFG)
    assert all(r.rule != "rolling_sharpe_below_threshold" for r in recs)


def test_drawdown_breach_triggers_recommendation() -> None:
    # one catastrophic trade: -30% > 20% limit; positive Sharpe otherwise
    returns = [0.02] * 12 + [-0.30] + [0.02] * 12
    recs = evaluate_strategy("crash", returns, CFG)
    rec = next(r for r in recs if r.rule == "max_drawdown_breach")
    assert rec.severity == "critical"  # 30% >= 1.5 * 20%
    assert rec.metrics["max_drawdown"] >= 0.30


def test_recommendation_never_contains_apply_side_effect() -> None:
    # The model is advisory-only by construction: action is 'disable'
    # (a recommendation), and there is no field that could carry state.
    rec = Recommendation(strategy_key="x", rule="r", reason="because")
    assert rec.action == "disable"
    assert set(rec.model_dump()) == {
        "strategy_key", "action", "rule", "reason", "severity", "metrics",
    }
