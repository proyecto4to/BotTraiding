"""Golden-path validation: the real sma_crossover strategy from the shared
trading_strategies registry, run end-to-end through the engine.

- On strongly trending synthetic data the strategy must be profitable with
  sane metrics.
- On mean-reverting (range) data the SAME configuration must show clearly
  degraded performance (crossovers whipsaw).
- Higher slippage must produce strictly worse net PnL (cost monotonicity).
"""

from __future__ import annotations

import pytest

from trading_strategies import load_builtin_strategies

from app.data import generate_synthetic_bars
from app.engine import BacktestConfig, FrictionConfig, run_backtest

registry = load_builtin_strategies()

FRICTION = FrictionConfig(spread_bps=2.0, slippage_bps=1.0, commission_bps=1.0)


def _run(regime: str, slippage_bps: float = 1.0, seed: int = 7):
    bars = generate_synthetic_bars(
        regime=regime,
        n_bars=700,
        seed=seed,
        start_price=100.0,
        drift=0.004,
        volatility=0.008,
        mean_reversion=0.15,
        timeframe="1h",
    )
    strategy = registry.create("sma_crossover", {"fast_period": 10, "slow_period": 30})
    config = BacktestConfig(
        initial_capital=100_000.0,
        friction=FrictionConfig(
            spread_bps=FRICTION.spread_bps,
            slippage_bps=slippage_bps,
            commission_bps=FRICTION.commission_bps,
        ),
    )
    return run_backtest(strategy, bars, config)


def test_sma_crossover_is_profitable_on_trending_data() -> None:
    result = _run("trend")
    m = result.metrics
    assert m["trade_count"] >= 1
    assert m["total_return"] > 0.0
    assert m["final_equity"] > 100_000.0
    assert m["sharpe"] > 0.0
    assert m["cagr"] > 0.0
    assert 0.0 <= m["max_drawdown"] < 0.6
    assert 0.0 <= m["win_rate"] <= 1.0
    assert 0.0 < m["exposure_pct"] <= 100.0
    # every trade is fully accounted for
    for trade in result.trades:
        assert trade["exit_reason"] in {
            "stop_loss", "take_profit", "opposite_signal", "end_of_data"
        }


def test_sma_crossover_degrades_on_mean_reverting_data() -> None:
    trend = _run("trend").metrics
    rng = _run("range").metrics
    # The engine must show the whipsaw: clearly worse than on the trend...
    assert rng["total_return"] < trend["total_return"]
    assert rng["sharpe"] < trend["sharpe"]
    # ...and not accidentally a great strategy on ranging data.
    assert rng["total_return"] < 0.05


def test_higher_slippage_means_worse_net_pnl_full_strategy() -> None:
    finals = [
        _run("trend", slippage_bps=s).metrics["final_equity"]
        for s in (0.0, 10.0, 40.0)
    ]
    assert finals[0] > finals[1] > finals[2]


def test_no_lookahead_smoke_equity_flat_until_first_fill() -> None:
    result = _run("trend")
    trades = result.trades
    assert trades, "expected at least one trade"
    first_entry = trades[0]["entry_time"]
    # every equity point strictly before the first fill equals initial capital
    for point in result.equity_curve:
        if point["timestamp"] < first_entry:
            assert point["equity"] == pytest.approx(100_000.0)
        else:
            break
