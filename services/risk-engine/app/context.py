"""ValidationContext: everything a risk check needs, computed once.

Derivation rules
----------------
- entry_price: signal.metadata["price"], else the portfolio mark for the
  symbol; None if neither exists (price-dependent checks then fail safe).
- stop: signal.stop_loss, else ATR-derived (metadata["atr"] x multiple).
- Exposure deltas are signed-position aware: a signal that reduces an
  existing position lowers the projected exposure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app import sizing
from app.schemas import ExtendedRiskLimits, PortfolioStateIn, StopPlan
from trading_contracts import OrderSide, TradeSignal


def _meta_float(signal: TradeSignal, key: str) -> Optional[float]:
    value = signal.metadata.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class ValidationContext:
    signal: TradeSignal
    limits: ExtendedRiskLimits
    state: PortfolioStateIn
    account_id: str

    entry_price: Optional[float] = None
    stop_plan: StopPlan = field(default_factory=StopPlan)
    stop_price: Optional[float] = None

    equity: float = 0.0
    current_position_qty: float = 0.0
    signed_qty: float = 0.0
    qty_after: float = 0.0
    proposed_notional: float = 0.0

    symbol_exposure_before: float = 0.0
    symbol_exposure_after: float = 0.0
    symbol_exposure_delta: float = 0.0
    gross_exposure_after: float = 0.0
    sector: str = "unknown"
    sector_exposure_after: float = 0.0

    @property
    def increases_exposure(self) -> bool:
        return abs(self.qty_after) > abs(self.current_position_qty)

    @property
    def new_symbol_returns(self) -> Optional[list[float]]:
        meta = self.signal.metadata.get("returns")
        if isinstance(meta, list) and len(meta) >= 2:
            try:
                return [float(x) for x in meta]
            except (TypeError, ValueError):
                return None
        series = self.state.returns.get(self.signal.symbol)
        if series and len(series) >= 2:
            return series
        return None


def build_context(
    signal: TradeSignal,
    limits: ExtendedRiskLimits,
    state: PortfolioStateIn,
    account_id: str,
) -> ValidationContext:
    ctx = ValidationContext(signal=signal, limits=limits, state=state, account_id=account_id)

    ctx.equity = state.account.equity
    ctx.entry_price = _meta_float(signal, "price")
    if ctx.entry_price is None:
        ctx.entry_price = state.marks.get(signal.symbol)

    ctx.stop_plan = sizing.plan_stops(
        signal.side,
        ctx.entry_price,
        signal.stop_loss,
        atr=_meta_float(signal, "atr"),
        atr_multiple=_meta_float(signal, "atr_stop_multiple") or sizing.DEFAULT_ATR_STOP_MULTIPLE,
        current_price=_meta_float(signal, "current_price"),
        trail_distance=_meta_float(signal, "trail_distance"),
        break_even_trigger_r=_meta_float(signal, "break_even_trigger_r") or 1.0,
        break_even_offset=_meta_float(signal, "break_even_offset") or 0.0,
    )
    ctx.stop_price = ctx.stop_plan.initial_stop

    for position in state.positions:
        if position.symbol == signal.symbol:
            ctx.current_position_qty = position.quantity
            break

    ctx.signed_qty = signal.suggested_size * (1.0 if signal.side == OrderSide.BUY else -1.0)
    ctx.qty_after = ctx.current_position_qty + ctx.signed_qty

    price = ctx.entry_price or 0.0
    ctx.proposed_notional = signal.suggested_size * price

    ctx.symbol_exposure_before = state.exposure.per_symbol.get(
        signal.symbol, abs(ctx.current_position_qty) * price
    )
    ctx.symbol_exposure_after = abs(ctx.qty_after) * price
    if price == 0.0:
        # No price -> cannot project; keep current exposure (price-dependent
        # checks fail on their own).
        ctx.symbol_exposure_after = ctx.symbol_exposure_before
    ctx.symbol_exposure_delta = ctx.symbol_exposure_after - ctx.symbol_exposure_before
    ctx.gross_exposure_after = max(
        0.0, state.exposure.gross_exposure + ctx.symbol_exposure_delta
    )

    ctx.sector = str(signal.metadata.get("sector", "unknown"))
    sector_before = state.exposure.per_sector.get(ctx.sector, 0.0)
    ctx.sector_exposure_after = max(0.0, sector_before + ctx.symbol_exposure_delta)

    return ctx
