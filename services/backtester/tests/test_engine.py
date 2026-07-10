"""Engine behaviour tests: fill timing (no look-ahead), gaps, conservative
stop-first ordering, liquidity caps, sessions, reversals, frictions.

All scenarios use the ScriptedStrategy stub and zero frictions unless the
friction itself is under test, so every expected number is hand-computable.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from trading_contracts import OrderSide

from app.engine import (
    BacktestConfig,
    EngineError,
    FrictionConfig,
    SessionWindow,
    run_backtest,
)
from tests.utils import T0, ScriptedStrategy, buy, flat_bars, make_bars, sell


def ts(i: int, minutes: int = 60):
    return T0 + timedelta(minutes=minutes * i)


def cfg(**kwargs) -> BacktestConfig:
    kwargs.setdefault("initial_capital", 10_000.0)
    return BacktestConfig(**kwargs)


# --- no look-ahead ------------------------------------------------------------------


def test_signal_at_bar_n_fills_at_bar_n_plus_1_open() -> None:
    bars = make_bars([
        (100.0, 101.0, 99.0, 100.5, 10_000),
        (100.5, 101.5, 99.5, 101.0, 10_000),
        (101.0, 102.0, 100.0, 101.5, 10_000),
        (102.0, 103.0, 101.0, 102.5, 10_000),  # <- fill expected here, at 102.0
        (102.5, 103.5, 101.5, 103.0, 10_000),
        (103.0, 104.0, 102.0, 103.5, 10_000),
    ])
    strategy = ScriptedStrategy({ts(2): buy()})
    result = run_backtest(strategy, bars, cfg())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["entry_time"] == ts(3).isoformat()
    assert trade["avg_entry_price"] == pytest.approx(102.0)  # bar N+1 OPEN
    # Before the fill bar the account must be flat: no look-ahead PnL at bar N.
    assert result.equity_curve[2]["equity"] == pytest.approx(10_000.0)
    assert result.equity_curve[3]["equity"] != pytest.approx(10_000.0)


def test_configurable_latency_fill_delay_two_bars() -> None:
    bars = flat_bars(6)
    bars = make_bars([
        (100.0, 101.0, 99.0, 100.0, 10_000),
        (100.0, 101.0, 99.0, 100.0, 10_000),
        (100.0, 101.0, 99.0, 100.0, 10_000),
        (100.0, 101.0, 99.0, 100.0, 10_000),
        (104.0, 105.0, 103.0, 104.0, 10_000),  # distinct open to detect the fill
        (104.0, 105.0, 103.0, 104.0, 10_000),
    ])
    strategy = ScriptedStrategy({ts(2): buy()})
    result = run_backtest(
        strategy, bars, cfg(friction=FrictionConfig(fill_delay_bars=2))
    )
    assert result.trades[0]["entry_time"] == ts(4).isoformat()
    assert result.trades[0]["avg_entry_price"] == pytest.approx(104.0)


def test_signal_at_last_bar_never_fills() -> None:
    bars = flat_bars(4)
    strategy = ScriptedStrategy({ts(3): buy()})
    result = run_backtest(strategy, bars, cfg())
    assert result.trades == []
    # the engine does not even evaluate the last bar: nothing could ever fill
    assert result.stats["signals_generated"] == 0
    assert ts(3) not in strategy.evaluations


# --- gaps -----------------------------------------------------------------------------


def test_gap_through_stop_fills_at_gapped_open_not_stop_level() -> None:
    bars = make_bars([
        (100.0, 101.0, 99.0, 100.0, 10_000),
        (100.0, 101.0, 99.0, 100.0, 10_000),   # entry at open 100
        (90.0, 92.0, 88.0, 91.0, 10_000),      # opens BELOW the 95 stop
    ])
    strategy = ScriptedStrategy({ts(0): buy(stop_loss=95.0)})
    result = run_backtest(strategy, bars, cfg())
    trade = result.trades[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["avg_exit_price"] == pytest.approx(90.0)  # gapped open, not 95
    assert trade["exit_time"] == ts(2).isoformat()


def test_gap_through_target_fills_at_gapped_open() -> None:
    bars = make_bars([
        (100.0, 101.0, 99.0, 100.0, 10_000),
        (100.0, 101.0, 99.0, 100.0, 10_000),   # entry at open 100
        (108.0, 109.0, 107.0, 108.0, 10_000),  # opens ABOVE the 105 target
    ])
    strategy = ScriptedStrategy({ts(0): buy(stop_loss=95.0, take_profit=105.0)})
    result = run_backtest(strategy, bars, cfg())
    trade = result.trades[0]
    assert trade["exit_reason"] == "take_profit"
    assert trade["avg_exit_price"] == pytest.approx(108.0)


# --- conservative intra-bar ordering ---------------------------------------------------


def test_stop_fills_first_when_both_stop_and_target_touch_long() -> None:
    bars = make_bars([
        (100.0, 100.0, 100.0, 100.0, 10_000),
        (100.0, 100.0, 100.0, 100.0, 10_000),  # entry at 100
        (100.0, 106.0, 94.0, 100.0, 10_000),   # touches BOTH 95 stop and 105 tp
    ])
    strategy = ScriptedStrategy({ts(0): buy(stop_loss=95.0, take_profit=105.0)})
    result = run_backtest(strategy, bars, cfg())
    trade = result.trades[0]
    assert trade["exit_reason"] == "stop_loss"  # worst case wins
    assert trade["avg_exit_price"] == pytest.approx(95.0)


def test_stop_fills_first_when_both_touch_short() -> None:
    bars = make_bars([
        (100.0, 100.0, 100.0, 100.0, 10_000),
        (100.0, 100.0, 100.0, 100.0, 10_000),  # short entry at 100
        (100.0, 106.0, 94.0, 100.0, 10_000),   # touches BOTH 105 stop and 95 tp
    ])
    strategy = ScriptedStrategy({ts(0): sell(stop_loss=105.0, take_profit=95.0)})
    result = run_backtest(strategy, bars, cfg())
    trade = result.trades[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["avg_exit_price"] == pytest.approx(105.0)


def test_take_profit_fills_when_only_target_touches() -> None:
    bars = make_bars([
        (100.0, 100.0, 100.0, 100.0, 10_000),
        (100.0, 100.0, 100.0, 100.0, 10_000),
        (100.0, 106.0, 99.0, 105.0, 10_000),  # only the 105 target trades
    ])
    strategy = ScriptedStrategy({ts(0): buy(stop_loss=95.0, take_profit=105.0)})
    result = run_backtest(strategy, bars, cfg())
    trade = result.trades[0]
    assert trade["exit_reason"] == "take_profit"
    assert trade["avg_exit_price"] == pytest.approx(105.0)


def test_stop_checked_on_the_entry_bar_itself() -> None:
    # The fill happens at the open (first price of the bar); the rest of the
    # bar can stop it out immediately.
    bars = make_bars([
        (100.0, 100.0, 100.0, 100.0, 10_000),
        (100.0, 101.0, 93.0, 94.0, 10_000),  # entry at 100, low 93 < stop 95
    ])
    strategy = ScriptedStrategy({ts(0): buy(stop_loss=95.0)})
    result = run_backtest(strategy, bars, cfg())
    trade = result.trades[0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["entry_time"] == trade["exit_time"] == ts(1).isoformat()
    assert trade["avg_exit_price"] == pytest.approx(95.0)


# --- liquidity cap ----------------------------------------------------------------------


def test_liquidity_cap_drops_unfilled_remainder_by_default() -> None:
    bars = flat_bars(5, price=100.0, volume=1_000.0)
    strategy = ScriptedStrategy({ts(0): buy()})
    config = cfg(
        initial_capital=100_000.0,  # desired qty = 1000 > cap 0.1 * vol 1000 = 100
        friction=FrictionConfig(max_participation=0.1),
    )
    result = run_backtest(strategy, bars, config)
    trade = result.trades[0]
    assert trade["quantity"] == pytest.approx(100.0)
    assert result.stats["entry_qty_dropped_liquidity"] == pytest.approx(900.0)


def test_liquidity_cap_carries_remainder_when_configured() -> None:
    bars = flat_bars(5, price=100.0, volume=1_000.0)
    strategy = ScriptedStrategy({ts(0): buy()})
    config = cfg(
        initial_capital=100_000.0,
        friction=FrictionConfig(max_participation=0.1, carry_unfilled=True),
    )
    result = run_backtest(strategy, bars, config)
    trade = result.trades[0]
    # 100 units at each of bars 1..4 opens; then closed at end of data
    assert trade["quantity"] == pytest.approx(400.0)
    assert trade["exit_reason"] == "end_of_data"
    assert result.stats["entry_qty_dropped_liquidity"] == pytest.approx(0.0)


def test_liquidity_capped_exit_keeps_unwinding_next_bars() -> None:
    # Position of 100 units, but exit bars only allow 0.05 * 1000 = 50/bar.
    bars = flat_bars(6, price=100.0, volume=1_000.0)
    strategy = ScriptedStrategy({ts(0): buy(), ts(2): sell()})
    config = cfg(
        initial_capital=10_000.0,
        friction=FrictionConfig(max_participation=0.05),
        allow_reverse=False,
    )
    result = run_backtest(strategy, bars, config)
    trade = result.trades[0]
    assert trade["quantity"] == pytest.approx(50.0)  # capped entry: 0.05*1000
    assert trade["exit_reason"] == "opposite_signal"


# --- frictions --------------------------------------------------------------------------


def test_friction_costs_hand_computed() -> None:
    # spread 20bps (half = 10bps) + slippage 10bps => +/- 20bps per fill.
    bars = flat_bars(5, price=100.0, volume=1_000_000.0)
    strategy = ScriptedStrategy({ts(0): buy()})
    config = cfg(
        initial_capital=10_000.0,
        position_size_pct=0.5,
        friction=FrictionConfig(
            spread_bps=20.0, slippage_bps=10.0,
            commission_bps=10.0, commission_per_unit=0.01,
        ),
    )
    result = run_backtest(strategy, bars, config)
    trade = result.trades[0]

    qty = 5_000.0 / 100.2                      # sized on the adjusted open
    entry_commission = qty * 100.2 * 0.001 + qty * 0.01
    exit_commission = qty * 99.8 * 0.001 + qty * 0.01
    expected_net = (99.8 - 100.2) * qty - entry_commission - exit_commission

    assert trade["avg_entry_price"] == pytest.approx(100.2)   # buy pays up
    assert trade["avg_exit_price"] == pytest.approx(99.8)     # sell receives less
    assert trade["quantity"] == pytest.approx(qty)
    assert trade["net_pnl"] == pytest.approx(expected_net)
    assert result.equity_curve[-1]["equity"] == pytest.approx(10_000.0 + expected_net)


def test_size_impact_term_hand_computed() -> None:
    # participation 500/1000 = 0.5 -> extra 100 * 0.5 = 50bps adverse.
    bars = flat_bars(4, price=100.0, volume=1_000.0)
    strategy = ScriptedStrategy({ts(0): buy()})
    config = cfg(
        initial_capital=50_000.0,
        friction=FrictionConfig(size_impact_bps=100.0),
    )
    result = run_backtest(strategy, bars, config)
    assert result.trades[0]["avg_entry_price"] == pytest.approx(100.0 * 1.005)


def test_higher_slippage_means_worse_net_pnl() -> None:
    bars = make_bars([
        (100.0, 101.0, 99.0, 100.0, 100_000),
        (100.0, 103.0, 99.0, 102.0, 100_000),
        (102.0, 105.0, 101.0, 104.0, 100_000),
        (104.0, 107.0, 103.0, 106.0, 100_000),
        (106.0, 109.0, 105.0, 108.0, 100_000),
    ])
    strategy_script = {ts(0): buy(), ts(3): sell()}
    finals = []
    for slippage in (0.0, 10.0, 50.0):
        result = run_backtest(
            ScriptedStrategy(strategy_script),
            bars,
            cfg(friction=FrictionConfig(slippage_bps=slippage), allow_reverse=False),
        )
        finals.append(result.equity_curve[-1]["equity"])
    assert finals[0] > finals[1] > finals[2]  # monotonically worse


# --- trading-hours filter -----------------------------------------------------------------


def test_signals_outside_session_are_skipped() -> None:
    bars = flat_bars(48)  # 2 days of hourly bars starting 00:00 UTC
    sessions = [SessionWindow(start="09:00", end="17:00")]
    # 03:00 is outside the session: the strategy is not even evaluated there.
    strategy = ScriptedStrategy({ts(3): buy(), ts(10): buy()})
    result = run_backtest(strategy, bars, cfg(sessions=sessions))
    assert result.stats["signals_generated"] == 1  # only the 10:00 signal
    assert result.stats["signals_skipped_out_of_session"] > 0
    assert ts(3) not in strategy.evaluations
    assert len(result.trades) == 1
    assert result.trades[0]["entry_time"] == ts(11).isoformat()  # 11:00, in session


def test_entry_fill_is_deferred_to_next_in_session_bar() -> None:
    bars = flat_bars(48)
    sessions = [SessionWindow(start="09:00", end="17:00")]
    # Signal at 16:00; the next bar (17:00) is already outside the session,
    # so the fill waits for the 09:00 open of the next day (index 33).
    strategy = ScriptedStrategy({ts(16): buy()})
    result = run_backtest(strategy, bars, cfg(sessions=sessions))
    assert len(result.trades) == 1
    assert result.trades[0]["entry_time"] == ts(33).isoformat()


def test_session_days_filter() -> None:
    # T0 = 2024-01-01 is a Monday (weekday 0). Only allow Tuesday.
    bars = flat_bars(48)
    sessions = [SessionWindow(start="00:00", end="23:59", days=[1])]
    strategy = ScriptedStrategy({ts(5): buy()})  # Monday 05:00 -> skipped
    result = run_backtest(strategy, bars, cfg(sessions=sessions))
    assert result.stats["signals_generated"] == 0
    assert result.trades == []


# --- position management --------------------------------------------------------------------


def test_opposite_signal_closes_and_reverses() -> None:
    bars = flat_bars(8)
    strategy = ScriptedStrategy({ts(0): buy(), ts(3): sell()})
    result = run_backtest(strategy, bars, cfg())
    assert len(result.trades) == 2
    long_trade, short_trade = result.trades
    assert long_trade["side"] == "buy"
    assert long_trade["exit_reason"] == "opposite_signal"
    assert long_trade["exit_time"] == ts(4).isoformat()
    assert short_trade["side"] == "sell"
    assert short_trade["entry_time"] == ts(4).isoformat()
    assert short_trade["exit_reason"] == "end_of_data"


def test_opposite_signal_close_only_when_reverse_disabled() -> None:
    bars = flat_bars(8)
    strategy = ScriptedStrategy({ts(0): buy(), ts(3): sell()})
    result = run_backtest(strategy, bars, cfg(allow_reverse=False))
    assert len(result.trades) == 1
    assert result.trades[0]["exit_reason"] == "opposite_signal"
    # flat prices + no frictions: round trip at 100 leaves capital unchanged
    assert result.equity_curve[-1]["equity"] == pytest.approx(10_000.0)


def test_same_side_signal_is_ignored_while_positioned() -> None:
    bars = flat_bars(8)
    strategy = ScriptedStrategy({ts(0): buy(), ts(3): buy()})
    result = run_backtest(strategy, bars, cfg())
    assert len(result.trades) == 1  # one position per symbol/strategy
    assert result.stats["signals_ignored_same_side"] == 1


def test_end_of_data_closes_at_last_close_and_marks_equity() -> None:
    bars = make_bars([
        (100.0, 101.0, 99.0, 100.0, 10_000),
        (100.0, 101.0, 99.0, 100.0, 10_000),   # entry at 100
        (100.0, 103.0, 99.0, 102.0, 10_000),
        (102.0, 105.0, 101.0, 104.0, 10_000),  # forced close at close 104
    ])
    strategy = ScriptedStrategy({ts(0): buy()})
    result = run_backtest(strategy, bars, cfg())
    trade = result.trades[0]
    assert trade["exit_reason"] == "end_of_data"
    assert trade["avg_exit_price"] == pytest.approx(104.0)
    qty = 10_000.0 / 100.0
    assert result.equity_curve[-1]["equity"] == pytest.approx(10_000.0 + qty * 4.0)
    assert result.metrics["trade_count"] == 1
    assert result.metrics["exposure_pct"] > 0.0


def test_engine_rejects_empty_or_unsorted_bars() -> None:
    with pytest.raises(EngineError):
        run_backtest(ScriptedStrategy({}), [], cfg())
    bars = flat_bars(3)
    bars.reverse()
    with pytest.raises(EngineError):
        run_backtest(ScriptedStrategy({}), bars, cfg())
