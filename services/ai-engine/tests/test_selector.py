"""Selector affinity math: known inputs -> expected ranking and weights."""

from __future__ import annotations

import math

import pytest

from app.regime import RegimeState
from app.selector import (
    PerformanceRecord,
    StrategyInfo,
    category_affinity,
    performance_score,
    rank_strategies,
    registry_strategies,
)


def regime(trend: str = "up", vol: str = "normal") -> RegimeState:
    return RegimeState(trend=trend, volatility=vol, confidence=0.8)


TREND_STRAT = StrategyInfo(key="a_trend", category="trend")
MR_STRAT = StrategyInfo(key="b_meanrev", category="mean_reversion")
VOL_STRAT = StrategyInfo(key="c_vol", category="volatility")


def test_affinity_matrix_known_values() -> None:
    # trend category in an up/normal regime: 1.0 * 1.0
    assert category_affinity("trend", regime("up", "normal")) == pytest.approx(1.0)
    # mean reversion in sideways/normal: 1.0 * 1.0
    assert category_affinity("mean_reversion", regime("sideways", "normal")) == pytest.approx(1.0)
    # trend in sideways/normal: 0.2 * 1.0
    assert category_affinity("trend", regime("sideways", "normal")) == pytest.approx(0.2)
    # unknown category falls back to neutral 0.5 * 0.5
    assert category_affinity("does_not_exist", regime()) == pytest.approx(0.25)


def test_performance_score_is_logistic_in_sharpe() -> None:
    assert performance_score(None) == pytest.approx(0.5)
    zero = PerformanceRecord(strategy_key="x", sharpe=0.0)
    assert performance_score(zero) == pytest.approx(0.5)
    good = PerformanceRecord(strategy_key="x", sharpe=2.0)
    assert performance_score(good) == pytest.approx(1.0 / (1.0 + math.exp(-2.0)))
    bad = PerformanceRecord(strategy_key="x", sharpe=-2.0)
    assert performance_score(bad) < 0.2


def test_regime_dominates_with_equal_performance() -> None:
    perf = [
        PerformanceRecord(strategy_key="a_trend", sharpe=1.0),
        PerformanceRecord(strategy_key="b_meanrev", sharpe=1.0),
    ]
    up = rank_strategies(regime("up"), [TREND_STRAT, MR_STRAT], perf)
    assert [s.key for s in up] == ["a_trend", "b_meanrev"]

    sideways = rank_strategies(regime("sideways"), [TREND_STRAT, MR_STRAT], perf)
    assert [s.key for s in sideways] == ["b_meanrev", "a_trend"]


def test_performance_breaks_ties_within_category() -> None:
    s1 = StrategyInfo(key="trend_good", category="trend")
    s2 = StrategyInfo(key="trend_bad", category="trend")
    perf = [
        PerformanceRecord(strategy_key="trend_good", sharpe=2.0),
        PerformanceRecord(strategy_key="trend_bad", sharpe=-1.0),
    ]
    ranked = rank_strategies(regime("up"), [s1, s2], perf)
    assert [s.key for s in ranked] == ["trend_good", "trend_bad"]
    assert ranked[0].weight > ranked[1].weight


def test_expected_score_math() -> None:
    # up/high regime, volatility strategy with sharpe 0 (neutral 0.5):
    # affinity = 0.5 (trend) * 1.0 (vol) = 0.5 -> score = 0.25
    perf = [PerformanceRecord(strategy_key="c_vol", sharpe=0.0)]
    ranked = rank_strategies(regime("up", "high"), [VOL_STRAT], perf)
    assert ranked[0].affinity == pytest.approx(0.5)
    assert ranked[0].score == pytest.approx(0.25)
    assert ranked[0].weight == pytest.approx(1.0)


def test_weights_sum_to_one_and_top_n() -> None:
    strategies = [TREND_STRAT, MR_STRAT, VOL_STRAT]
    ranked = rank_strategies(regime("up", "low"), strategies, [])
    assert sum(s.weight for s in ranked) == pytest.approx(1.0)

    top2 = rank_strategies(regime("up", "low"), strategies, [], top_n=2)
    assert len(top2) == 2
    assert sum(s.weight for s in top2) == pytest.approx(1.0)


def test_missing_performance_gets_neutral_score() -> None:
    ranked = rank_strategies(regime("up"), [TREND_STRAT], [])
    assert ranked[0].perf_score == pytest.approx(0.5)


def test_registry_strategies_loads_shared_library() -> None:
    infos = registry_strategies()
    assert len(infos) >= 16
    assert all(info.category for info in infos)
