"""Sizing math (known inputs -> exact expected size) and stop calculations
(trailing / break-even / ATR-derived plans)."""

from __future__ import annotations

import pytest

from app.sizing import (
    apply_break_even,
    compute_position_size,
    compute_trailing_stop,
    plan_stops,
)
from trading_contracts import OrderSide


# --- position size -----------------------------------------------------------


def test_risk_based_size_exact():
    # 1% of 100k = 1000 risk; stop distance 5 -> 200 units
    result = compute_position_size(100_000, 0.01, 100.0, 95.0)
    assert result.risk_amount == pytest.approx(1000.0)
    assert result.stop_distance == pytest.approx(5.0)
    assert result.size_by_risk == pytest.approx(200.0)
    assert result.max_size_allowed == pytest.approx(200.0)
    assert result.binding_constraint == "risk"


def test_size_capped_by_symbol_exposure_room():
    result = compute_position_size(100_000, 0.01, 100.0, 95.0, symbol_room=15_000)
    assert result.max_size_allowed == pytest.approx(150.0)
    assert result.binding_constraint == "exposure_symbol"
    assert result.caps["risk"] == pytest.approx(200.0)


def test_size_capped_by_margin_room():
    result = compute_position_size(100_000, 0.01, 100.0, 95.0, margin_room=5_000)
    assert result.max_size_allowed == pytest.approx(50.0)
    assert result.binding_constraint == "margin"


def test_size_capped_by_tightest_constraint():
    result = compute_position_size(
        100_000,
        0.01,
        100.0,
        95.0,
        symbol_room=15_000,
        leverage_room=8_000,
        total_room=12_000,
        margin_room=20_000,
    )
    assert result.max_size_allowed == pytest.approx(80.0)
    assert result.binding_constraint == "leverage"


def test_negative_room_yields_zero_size():
    result = compute_position_size(100_000, 0.01, 100.0, 95.0, symbol_room=-500)
    assert result.max_size_allowed == 0.0


def test_no_stop_yields_zero_size():
    result = compute_position_size(100_000, 0.01, 100.0, None)
    assert result.max_size_allowed == 0.0
    assert result.binding_constraint == "no_price_or_stop"


def test_zero_stop_distance_yields_zero_size():
    result = compute_position_size(100_000, 0.01, 100.0, 100.0)
    assert result.max_size_allowed == 0.0
    assert result.binding_constraint == "zero_stop_distance"


# --- trailing stop -----------------------------------------------------------


def test_trailing_stop_long_moves_up():
    assert compute_trailing_stop(OrderSide.BUY, 110.0, 4.0, 95.0) == pytest.approx(106.0)


def test_trailing_stop_long_never_loosens():
    assert compute_trailing_stop(OrderSide.BUY, 100.0, 4.0, 106.0) == pytest.approx(106.0)


def test_trailing_stop_short_moves_down():
    assert compute_trailing_stop(OrderSide.SELL, 90.0, 4.0, 105.0) == pytest.approx(94.0)


def test_trailing_stop_short_never_loosens():
    assert compute_trailing_stop(OrderSide.SELL, 100.0, 4.0, 94.0) == pytest.approx(94.0)


def test_trailing_stop_without_existing_stop():
    assert compute_trailing_stop(OrderSide.BUY, 110.0, 4.0, None) == pytest.approx(106.0)


# --- break-even --------------------------------------------------------------


def test_break_even_activates_at_one_r():
    stop, active = apply_break_even(OrderSide.BUY, 100.0, 105.0, 95.0, 5.0, trigger_r=1.0)
    assert active is True
    assert stop == pytest.approx(100.0)


def test_break_even_not_triggered_below_r():
    stop, active = apply_break_even(OrderSide.BUY, 100.0, 104.99, 95.0, 5.0, trigger_r=1.0)
    assert active is False
    assert stop == pytest.approx(95.0)


def test_break_even_with_offset():
    stop, active = apply_break_even(
        OrderSide.BUY, 100.0, 110.0, 95.0, 5.0, trigger_r=1.0, offset=0.5
    )
    assert active is True
    assert stop == pytest.approx(100.5)


def test_break_even_short_side():
    stop, active = apply_break_even(OrderSide.SELL, 100.0, 95.0, 105.0, 5.0, trigger_r=1.0)
    assert active is True
    assert stop == pytest.approx(100.0)


def test_break_even_never_loosens_tighter_stop():
    stop, active = apply_break_even(OrderSide.BUY, 100.0, 110.0, 103.0, 5.0, trigger_r=1.0)
    assert active is True
    assert stop == pytest.approx(103.0)  # existing stop already better than entry


# --- stop plan ---------------------------------------------------------------


def test_plan_atr_derived_initial_stop():
    plan = plan_stops(OrderSide.BUY, 100.0, None, atr=2.0, atr_multiple=2.0)
    assert plan.initial_stop == pytest.approx(96.0)
    assert plan.adjusted_stop == pytest.approx(96.0)


def test_plan_uses_signal_stop_when_given():
    plan = plan_stops(OrderSide.BUY, 100.0, 95.0, atr=2.0)
    assert plan.initial_stop == pytest.approx(95.0)


def test_plan_combines_trailing_and_break_even():
    plan = plan_stops(
        OrderSide.BUY,
        100.0,
        96.0,
        current_price=110.0,
        trail_distance=4.0,
        break_even_trigger_r=1.0,
    )
    # trailing: 110 - 4 = 106 (beats initial 96 and break-even 100)
    assert plan.trailing_stop == pytest.approx(106.0)
    assert plan.break_even_active is True
    assert plan.break_even_stop == pytest.approx(100.0)
    assert plan.adjusted_stop == pytest.approx(106.0)


def test_plan_short_side_trailing():
    plan = plan_stops(
        OrderSide.SELL, 100.0, 104.0, current_price=92.0, trail_distance=4.0
    )
    assert plan.trailing_stop == pytest.approx(96.0)
    assert plan.adjusted_stop == pytest.approx(96.0)
