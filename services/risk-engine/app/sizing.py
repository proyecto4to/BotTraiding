"""Position sizing and stop management (dynamic / trailing / break-even).

Pure functions returning concrete numbers the execution layer uses:

- compute_position_size: risk-per-trade sizing (risk% x equity / stop
  distance) capped by exposure / leverage / total-exposure / margin rooms.
- compute_trailing_stop / apply_break_even: stop adjustment rules.
- plan_stops: composes initial (given or ATR-derived), trailing and
  break-even stops into a StopPlan; StopPlan.adjusted_stop is the effective
  stop and feeds RiskDecision.adjusted_stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.schemas import StopPlan
from trading_contracts import OrderSide

DEFAULT_ATR_STOP_MULTIPLE = 2.0


@dataclass
class SizingResult:
    size_by_risk: float = 0.0
    max_size_allowed: float = 0.0
    risk_amount: float = 0.0
    stop_distance: Optional[float] = None
    caps: dict[str, float] = field(default_factory=dict)
    binding_constraint: Optional[str] = None


def compute_position_size(
    equity: float,
    risk_per_trade: float,
    entry_price: Optional[float],
    stop_price: Optional[float],
    *,
    symbol_room: Optional[float] = None,
    sector_room: Optional[float] = None,
    leverage_room: Optional[float] = None,
    total_room: Optional[float] = None,
    margin_room: Optional[float] = None,
) -> SizingResult:
    """max_size_allowed = min(risk-based size, notional rooms / entry price).

    Rooms are *additional notional* still available under each limit; a
    None room means "no constraint". Missing entry/stop or non-positive
    stop distance yields max_size_allowed = 0 (fail-safe: cannot size
    without a stop).
    """
    risk_amount = max(0.0, equity) * max(0.0, risk_per_trade)
    result = SizingResult(risk_amount=risk_amount)

    if entry_price is None or entry_price <= 0 or stop_price is None:
        result.binding_constraint = "no_price_or_stop"
        return result

    stop_distance = abs(entry_price - stop_price)
    result.stop_distance = stop_distance
    if stop_distance <= 0:
        result.binding_constraint = "zero_stop_distance"
        return result

    size_by_risk = risk_amount / stop_distance
    result.size_by_risk = size_by_risk

    caps: dict[str, float] = {"risk": size_by_risk}
    rooms = {
        "exposure_symbol": symbol_room,
        "exposure_sector": sector_room,
        "leverage": leverage_room,
        "exposure_total": total_room,
        "margin": margin_room,
    }
    for name, room in rooms.items():
        if room is not None:
            caps[name] = max(0.0, room) / entry_price

    binding = min(caps, key=lambda k: caps[k])
    result.caps = caps
    result.max_size_allowed = max(0.0, caps[binding])
    result.binding_constraint = binding
    return result


def compute_trailing_stop(
    side: OrderSide,
    current_price: float,
    trail_distance: float,
    current_stop: Optional[float] = None,
) -> float:
    """Trail the stop behind the current price; never loosens an existing
    stop (long: only moves up, short: only moves down)."""
    if side == OrderSide.BUY:
        candidate = current_price - trail_distance
        return candidate if current_stop is None else max(current_stop, candidate)
    candidate = current_price + trail_distance
    return candidate if current_stop is None else min(current_stop, candidate)


def apply_break_even(
    side: OrderSide,
    entry_price: float,
    current_price: float,
    stop_price: Optional[float],
    risk_per_unit: float,
    trigger_r: float = 1.0,
    offset: float = 0.0,
) -> tuple[Optional[float], bool]:
    """Once unrealized profit >= trigger_r * risk_per_unit, move the stop to
    entry (+/- offset). Returns (new_stop, activated). Never loosens."""
    if risk_per_unit <= 0:
        return stop_price, False

    profit = (current_price - entry_price) if side == OrderSide.BUY else (
        entry_price - current_price
    )
    if profit < trigger_r * risk_per_unit:
        return stop_price, False

    be_stop = entry_price + offset if side == OrderSide.BUY else entry_price - offset
    if stop_price is None:
        return be_stop, True
    if side == OrderSide.BUY:
        return max(stop_price, be_stop), True
    return min(stop_price, be_stop), True


def plan_stops(
    side: OrderSide,
    entry_price: Optional[float],
    stop_loss: Optional[float],
    *,
    atr: Optional[float] = None,
    atr_multiple: float = DEFAULT_ATR_STOP_MULTIPLE,
    current_price: Optional[float] = None,
    trail_distance: Optional[float] = None,
    break_even_trigger_r: float = 1.0,
    break_even_offset: float = 0.0,
) -> StopPlan:
    """Dynamic stop plan: initial stop (signal's, else ATR-derived), then
    trailing and break-even adjustments when a current price is known."""
    plan = StopPlan(
        break_even_trigger_r=break_even_trigger_r,
        break_even_offset=break_even_offset,
    )

    initial = stop_loss
    if initial is None and entry_price is not None and atr is not None and atr > 0:
        initial = (
            entry_price - atr * atr_multiple
            if side == OrderSide.BUY
            else entry_price + atr * atr_multiple
        )
    plan.initial_stop = initial
    effective = initial

    distance = trail_distance
    if distance is None and atr is not None and atr > 0:
        distance = atr * atr_multiple
    plan.trail_distance = distance

    if current_price is not None and distance is not None and distance > 0:
        trailing = compute_trailing_stop(side, current_price, distance, effective)
        plan.trailing_stop = trailing
        effective = trailing

    if current_price is not None and entry_price is not None and initial is not None:
        risk_per_unit = abs(entry_price - initial)
        be_stop, active = apply_break_even(
            side,
            entry_price,
            current_price,
            effective,
            risk_per_unit,
            trigger_r=break_even_trigger_r,
            offset=break_even_offset,
        )
        if active:
            plan.break_even_stop = (
                entry_price + break_even_offset
                if side == OrderSide.BUY
                else entry_price - break_even_offset
            )
            effective = be_stop
        plan.break_even_active = active

    plan.adjusted_stop = effective
    return plan
