"""Unit tests for app/metrics.py with hand-computed expected values.

Reference series used repeatedly below:
- returns r = [0.10, -0.05, 0.02]
  mean = 0.07 / 3 = 7/300
  sample variance (ddof=1) = ((23/300)^2 + (22/300)^2 + (1/300)^2) / 2
                           = (529 + 484 + 1) / 90000 / 2 = 507 / 90000
  Sharpe(252)  = (7/300) / sqrt(507/90000) * sqrt(252) = 7/sqrt(507)*sqrt(252)
               = 4.935068...
  downside dev = sqrt((0 + 0.0025 + 0) / 3) = sqrt(1/1200) = 0.0288675...
  Sortino(252) = (7/300) / sqrt(1/1200) * sqrt(252) = 12.831147...
- trade PnLs = [10, -5, 20, -10]
  profit factor = 30 / 15 = 2.0, expectancy = 15/4 = 3.75,
  win rate = 0.5, avg win = 15.0, avg loss = -7.5
"""

from __future__ import annotations

import math

import pytest

from app.metrics import (
    average_loss,
    average_win,
    bar_returns,
    cagr,
    calmar_ratio,
    expectancy,
    exposure_pct,
    max_drawdown,
    profit_factor,
    sharpe_ratio,
    sortino_ratio,
    summarize,
    win_rate,
)

R = [0.10, -0.05, 0.02]
PNLS = [10.0, -5.0, 20.0, -10.0]


def test_bar_returns_hand_computed() -> None:
    assert bar_returns([100.0, 110.0, 99.0]) == pytest.approx([0.10, -0.10])
    assert bar_returns([100.0]).size == 0


def test_sharpe_hand_computed() -> None:
    expected = 7.0 / math.sqrt(507.0) * math.sqrt(252.0)  # = 4.9350815...
    assert expected == pytest.approx(4.9350815, abs=1e-5)
    assert sharpe_ratio(R, periods_per_year=252.0) == pytest.approx(expected)


def test_sharpe_degenerate_cases() -> None:
    assert sharpe_ratio([], 252.0) == 0.0
    assert sharpe_ratio([0.01], 252.0) == 0.0
    assert sharpe_ratio([0.01, 0.01, 0.01], 252.0) == 0.0  # zero variance


def test_sortino_hand_computed() -> None:
    expected = (7.0 / 300.0) / math.sqrt(1.0 / 1200.0) * math.sqrt(252.0)
    assert expected == pytest.approx(12.8312119, abs=1e-5)
    assert sortino_ratio(R, periods_per_year=252.0) == pytest.approx(expected)


def test_sortino_no_downside_is_undefined() -> None:
    assert sortino_ratio([0.01, 0.02, 0.03], 252.0) is None


def test_max_drawdown_hand_computed() -> None:
    # peaks: 100,120,120,120,120 -> drawdowns 0, 0, 30/120, 15/120, 40/120
    assert max_drawdown([100.0, 120.0, 90.0, 105.0, 80.0]) == pytest.approx(1.0 / 3.0)
    assert max_drawdown([100.0, 110.0, 120.0]) == 0.0
    assert max_drawdown([]) == 0.0


def test_cagr_hand_computed() -> None:
    # 2 periods with 2 periods/year -> exactly one year: 121/100 - 1 = 0.21
    assert cagr([100.0, 110.0, 121.0], periods_per_year=2.0) == pytest.approx(0.21)
    # 2 periods with 4 periods/year -> half a year: 1.21^2 - 1 = 0.4641
    assert cagr([100.0, 110.0, 121.0], periods_per_year=4.0) == pytest.approx(0.4641)
    assert cagr([100.0], periods_per_year=252.0) == 0.0
    assert cagr([100.0, -5.0], periods_per_year=252.0) == -1.0


def test_calmar_hand_computed() -> None:
    assert calmar_ratio(0.21, 1.0 / 3.0) == pytest.approx(0.63)
    assert calmar_ratio(0.21, 0.0) is None


def test_profit_factor_hand_computed() -> None:
    assert profit_factor(PNLS) == pytest.approx(2.0)
    assert profit_factor([]) is None
    assert profit_factor([5.0, 10.0]) is None  # no losses -> undefined, not inf


def test_expectancy_and_win_rate_hand_computed() -> None:
    assert expectancy(PNLS) == pytest.approx(3.75)
    assert expectancy([]) == 0.0
    assert win_rate(PNLS) == pytest.approx(0.5)
    assert win_rate([]) == 0.0
    assert win_rate([0.0, 1.0]) == pytest.approx(0.5)  # zero-PnL trade is not a win


def test_avg_win_loss_hand_computed() -> None:
    assert average_win(PNLS) == pytest.approx(15.0)
    assert average_loss(PNLS) == pytest.approx(-7.5)
    assert average_win([-1.0]) is None
    assert average_loss([1.0]) is None


def test_exposure_pct_hand_computed() -> None:
    assert exposure_pct(25, 100) == pytest.approx(25.0)
    assert exposure_pct(0, 0) == 0.0


def test_summarize_shape_and_values() -> None:
    out = summarize([100.0, 110.0, 121.0], PNLS, periods_per_year=2.0, bars_in_position=2)
    assert out["total_return"] == pytest.approx(0.21)
    assert out["final_equity"] == pytest.approx(121.0)
    assert out["cagr"] == pytest.approx(0.21)
    assert out["max_drawdown"] == 0.0
    assert out["calmar"] is None  # no drawdown
    assert out["profit_factor"] == pytest.approx(2.0)
    assert out["expectancy"] == pytest.approx(3.75)
    assert out["win_rate"] == pytest.approx(0.5)
    assert out["trade_count"] == 4
    assert out["avg_win"] == pytest.approx(15.0)
    assert out["avg_loss"] == pytest.approx(-7.5)
    assert out["exposure_pct"] == pytest.approx(100.0 * 2 / 3)
    assert out["periods_per_year"] == 2.0
