"""Event-driven backtest engine (Fase 8).

Iterates Bars chronologically, feeds the strategy a growing (bounded)
window of history, collects the TradeSignals it proposes and simulates
execution with realistic frictions.

Fill-timing model (NO look-ahead bias):
- The strategy is evaluated once per bar N using only bars <= N.
- A TradeSignal generated at bar N becomes a pending market order that
  fills at the OPEN of bar N + ``fill_delay_bars`` (default 1). A signal
  can never fill at bar N's own open or close.
- ``stop_loss`` / ``take_profit`` from the TradeSignal ride with the open
  position as resting orders, so they DO fill intra-bar (no latency), the
  way a broker-side stop would.

Conservatism rules (documented choices):
- Intra-bar OHLC path is unknowable from bar data, so the worst case is
  assumed: if both the stop and the target are touched within the same
  bar, the STOP fills first.
- Gaps: if a bar OPENS beyond the stop (or target) level, the exit fills
  at the gapped open price, not at the theoretical level.
- Liquidity: each fill is capped at ``max_participation`` of the bar's
  volume. Unfilled ENTRY remainder is dropped (default) or carried to the
  next bar per ``carry_unfilled``. Unfilled EXIT remainder is always
  carried (a position cannot be "dropped"; it keeps unwinding at the next
  opens). The end-of-data forced close ignores the cap (final mark).

Position management:
- One open position per symbol/strategy run. Exits on opposite signal,
  stop, target, or end-of-data (forced close at the last bar's close).
  An opposite signal closes the position and, when ``allow_reverse`` is
  true (default), also opens a new position in the signalled direction.
- Sizing: entries invest ``position_size_pct`` of current equity at the
  fill bar's open (signals' ``suggested_size`` is advisory per
  docs/ARCHITECTURE.md principle 3). No leverage.
- Equity is marked to market at every bar close.

Trading-hours filter: when ``sessions`` is non-empty, the strategy is not
evaluated (signals skipped) and entries do not fill outside the session
windows; exits (stop/target/pending unwind) always remain active, as
risk-reduction is never gated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional, Protocol

from pydantic import BaseModel, Field, field_validator

from trading_contracts import Bar, OrderSide, TradeSignal

from app import metrics as metrics_mod

#: Annualization factors per timeframe (24/7 markets); fallback 252.
PERIODS_PER_YEAR_BY_TIMEFRAME: dict[str, float] = {
    "1m": 525_600.0,
    "5m": 105_120.0,
    "15m": 35_040.0,
    "30m": 17_520.0,
    "1h": 8_760.0,
    "4h": 2_190.0,
    "1d": 365.0,
}

_EPS = 1e-9


class EngineError(ValueError):
    """Raised on invalid engine input (unsorted/empty bars, bad config)."""


class SignalSource(Protocol):
    """Minimal strategy interface the engine needs (StrategyPlugin fits)."""

    def evaluate(
        self, bars: list[Bar], market: Optional[str] = None
    ) -> Optional[TradeSignal]: ...


# --- configuration -------------------------------------------------------------


class FrictionConfig(BaseModel):
    """Execution frictions, all configurable per run."""

    spread_bps: float = Field(default=0.0, ge=0.0, description="Full bid/ask spread in bps; fills pay half of it.")
    slippage_bps: float = Field(default=0.0, ge=0.0, description="Fixed adverse slippage in bps per fill.")
    size_impact_bps: float = Field(default=0.0, ge=0.0, description="Extra adverse bps x (fill_qty / bar_volume) - size impact term.")
    commission_bps: float = Field(default=0.0, ge=0.0, description="Commission as bps of fill notional.")
    commission_per_unit: float = Field(default=0.0, ge=0.0, description="Commission per unit/share/contract filled.")
    fill_delay_bars: int = Field(default=1, ge=1, description="Latency: a signal at bar N fills at bar N+delay's open. >= 1 enforces no look-ahead.")
    max_participation: Optional[float] = Field(default=None, gt=0.0, le=1.0, description="Liquidity cap: max fraction of bar volume per fill. None = uncapped.")
    carry_unfilled: bool = Field(default=False, description="Carry unfilled ENTRY remainder to next bars (True) or drop it (False).")


class SessionWindow(BaseModel):
    """One trading-hours window, evaluated on the bar's UTC timestamp."""

    start: str = Field(description="Session open 'HH:MM' (inclusive).")
    end: str = Field(description="Session close 'HH:MM' (exclusive). start > end wraps midnight.")
    days: Optional[list[int]] = Field(default=None, description="Allowed weekdays 0=Mon..6=Sun; None = all days.")

    @field_validator("start", "end")
    @classmethod
    def _valid_hhmm(cls, v: str) -> str:
        try:
            time.fromisoformat(v)
        except ValueError as exc:
            raise ValueError(f"'{v}' is not a valid HH:MM time") from exc
        return v

    @field_validator("days")
    @classmethod
    def _valid_days(cls, v: Optional[list[int]]) -> Optional[list[int]]:
        if v is not None and any(d < 0 or d > 6 for d in v):
            raise ValueError("days must be 0 (Mon) .. 6 (Sun)")
        return v

    def contains(self, ts: datetime) -> bool:
        if self.days is not None and ts.weekday() not in self.days:
            return False
        t = ts.time().replace(second=0, microsecond=0)
        start_t = time.fromisoformat(self.start)
        end_t = time.fromisoformat(self.end)
        if start_t <= end_t:
            return start_t <= t < end_t
        return t >= start_t or t < end_t  # overnight window


class BacktestConfig(BaseModel):
    """Full engine configuration for one run."""

    initial_capital: float = Field(default=100_000.0, gt=0.0)
    position_size_pct: float = Field(default=1.0, gt=0.0, le=1.0, description="Fraction of current equity invested per entry (no leverage).")
    allow_reverse: bool = Field(default=True, description="Opposite signal closes AND opens the reverse position (True) or closes only (False).")
    friction: FrictionConfig = Field(default_factory=FrictionConfig)
    sessions: list[SessionWindow] = Field(default_factory=list, description="Trading-hours windows; empty = always in session.")
    lookback_bars: int = Field(default=500, ge=10, le=10_000, description="Max history bars passed to the strategy per evaluation.")
    periods_per_year: Optional[float] = Field(default=None, gt=0.0, description="Annualization factor; None = inferred from the bars' timeframe.")
    risk_free_rate: float = Field(default=0.0, description="Per-period risk-free rate for Sharpe/Sortino.")
    market: Optional[str] = Field(default=None, description="Market hint passed to the strategy (e.g. 'crypto').")


# --- internal state -------------------------------------------------------------


@dataclass
class _PendingEntry:
    side: OrderSide
    signal_index: int
    earliest_index: int
    stop_loss: Optional[float]
    take_profit: Optional[float]
    remaining_qty: Optional[float] = None  # set once sizing happened (carry mode)


@dataclass
class _OpenTrade:
    side: OrderSide
    entry_index: int
    entry_time: datetime
    stop_loss: Optional[float]
    take_profit: Optional[float]
    entry_qty: float = 0.0
    entry_notional: float = 0.0
    exit_qty: float = 0.0
    exit_notional: float = 0.0
    commission: float = 0.0
    exit_reason: Optional[str] = None
    exit_index: Optional[int] = None
    exit_time: Optional[datetime] = None

    @property
    def open_qty(self) -> float:
        return self.entry_qty - self.exit_qty

    def to_record(self) -> dict:
        avg_entry = self.entry_notional / self.entry_qty
        avg_exit = self.exit_notional / self.exit_qty
        direction = 1.0 if self.side is OrderSide.BUY else -1.0
        gross = (avg_exit - avg_entry) * self.exit_qty * direction
        net = gross - self.commission
        notional = avg_entry * self.entry_qty
        return {
            "side": self.side.value,
            "quantity": round(self.entry_qty, 10),
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "entry_index": self.entry_index,
            "exit_index": self.exit_index,
            "avg_entry_price": avg_entry,
            "avg_exit_price": avg_exit,
            "gross_pnl": gross,
            "commission": self.commission,
            "net_pnl": net,
            "return_pct": (net / notional) if notional > 0 else 0.0,
            "exit_reason": self.exit_reason,
            "bars_held": (self.exit_index - self.entry_index) if self.exit_index is not None else None,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
        }


@dataclass
class EngineResult:
    equity_curve: list[dict]  # [{"timestamp": iso, "equity": float}, ...]
    trades: list[dict]
    metrics: dict
    stats: dict = field(default_factory=dict)


# --- engine ---------------------------------------------------------------------


class BacktestEngine:
    """Runs one strategy over one symbol's bar series. Not thread-safe;
    create one instance per run."""

    def __init__(self, strategy: SignalSource, bars: list[Bar], config: Optional[BacktestConfig] = None) -> None:
        if not bars:
            raise EngineError("no bars to backtest")
        for a, b in zip(bars, bars[1:]):
            if b.timestamp <= a.timestamp:
                raise EngineError("bars must be strictly ascending by timestamp")
        self.strategy = strategy
        self.bars = bars
        self.cfg = config or BacktestConfig()

        self._cash = self.cfg.initial_capital
        self._trade: Optional[_OpenTrade] = None
        self._pending_entry: Optional[_PendingEntry] = None
        self._exit_pending = False
        self._exit_reason: Optional[str] = None
        self._trades: list[dict] = []
        self._equity: list[float] = []
        self._timestamps: list[datetime] = []
        self._bars_in_position = 0
        self._stats = {
            "signals_generated": 0,
            "signals_skipped_out_of_session": 0,
            "signals_ignored_same_side": 0,
            "entry_qty_dropped_liquidity": 0.0,
        }

    # --- session helpers -----------------------------------------------------

    def _in_session(self, ts: datetime) -> bool:
        if not self.cfg.sessions:
            return True
        return any(w.contains(ts) for w in self.cfg.sessions)

    # --- fill mechanics --------------------------------------------------------

    def _fill_price(self, base: float, is_buy: bool, fill_qty: float, bar: Bar) -> float:
        f = self.cfg.friction
        participation = (fill_qty / bar.volume) if bar.volume > 0 else 0.0
        adverse_bps = f.spread_bps / 2.0 + f.slippage_bps + f.size_impact_bps * participation
        adj = adverse_bps / 10_000.0
        return base * (1.0 + adj) if is_buy else base * (1.0 - adj)

    def _cap_qty(self, desired: float, bar: Bar) -> float:
        cap = self.cfg.friction.max_participation
        if cap is None:
            return desired
        return min(desired, cap * bar.volume)

    def _commission(self, qty: float, price: float) -> float:
        f = self.cfg.friction
        return qty * price * f.commission_bps / 10_000.0 + qty * f.commission_per_unit

    def _apply_cash(self, is_buy: bool, qty: float, price: float) -> None:
        notional = qty * price
        self._cash += -notional if is_buy else notional
        self._cash -= self._commission(qty, price)

    # --- entry -------------------------------------------------------------------

    def _try_fill_entry(self, i: int, bar: Bar) -> None:
        pending = self._pending_entry
        if pending is None or i < pending.earliest_index or self._exit_pending:
            return
        if self._trade is not None and self._trade.side is not pending.side:
            return  # reverse still unwinding; exit path will re-trigger
        if not self._in_session(bar.timestamp):
            return  # entries only fill in-session; deferred to next in-session bar

        if pending.remaining_qty is None:
            # Size once, at first touch: fraction of current equity at the
            # friction-adjusted open (spread/slippage included, size impact
            # excluded to avoid a circular qty->price dependency).
            equity_now = self._cash + self._signed_open_qty() * bar.open
            est_price = self._fill_price(bar.open, pending.side is OrderSide.BUY, 0.0, bar)
            desired = (equity_now * self.cfg.position_size_pct) / est_price if est_price > 0 else 0.0
        else:
            desired = pending.remaining_qty
        if desired <= _EPS:
            self._pending_entry = None
            return

        fill_qty = self._cap_qty(desired, bar)
        remainder = desired - fill_qty
        if fill_qty <= _EPS:
            if not self.cfg.friction.carry_unfilled:
                self._stats["entry_qty_dropped_liquidity"] += remainder
                self._pending_entry = None
            else:
                pending.remaining_qty = desired
            return

        is_buy = pending.side is OrderSide.BUY
        price = self._fill_price(bar.open, is_buy, fill_qty, bar)
        self._apply_cash(is_buy, fill_qty, price)
        if self._trade is None:
            self._trade = _OpenTrade(
                side=pending.side,
                entry_index=i,
                entry_time=bar.timestamp,
                stop_loss=pending.stop_loss,
                take_profit=pending.take_profit,
            )
        self._trade.entry_qty += fill_qty
        self._trade.entry_notional += fill_qty * price
        self._trade.commission += self._commission(fill_qty, price)

        if remainder > _EPS and self.cfg.friction.carry_unfilled:
            pending.remaining_qty = remainder
        else:
            if remainder > _EPS:
                self._stats["entry_qty_dropped_liquidity"] += remainder
            self._pending_entry = None

    # --- exit --------------------------------------------------------------------

    def _fill_exit(self, i: int, bar: Bar, base_price: float, reason: str, capped: bool = True) -> None:
        trade = self._trade
        assert trade is not None
        desired = trade.open_qty
        if desired <= _EPS:
            return
        fill_qty = self._cap_qty(desired, bar) if capped else desired
        if fill_qty <= _EPS:
            self._exit_pending = True
            self._exit_reason = self._exit_reason or reason
            return
        is_buy = trade.side is OrderSide.SELL  # closing a short buys back
        price = self._fill_price(base_price, is_buy, fill_qty, bar)
        self._apply_cash(is_buy, fill_qty, price)
        trade.exit_qty += fill_qty
        trade.exit_notional += fill_qty * price
        trade.commission += self._commission(fill_qty, price)
        if trade.exit_reason is None:
            trade.exit_reason = reason
        trade.exit_index = i
        trade.exit_time = bar.timestamp

        if trade.open_qty <= _EPS:
            self._trades.append(trade.to_record())
            self._trade = None
            self._exit_pending = False
            self._exit_reason = None
        else:
            # Liquidity-capped exit: keep unwinding at the next bars' opens.
            self._exit_pending = True
            self._exit_reason = self._exit_reason or reason

    def _check_protective_exits(self, i: int, bar: Bar) -> None:
        """Stop/target intra-bar, conservative OHLC ordering + gap handling."""
        trade = self._trade
        assert trade is not None
        stop, target = trade.stop_loss, trade.take_profit
        if trade.side is OrderSide.BUY:
            if stop is not None and bar.open <= stop:
                self._fill_exit(i, bar, bar.open, "stop_loss")       # gapped through stop
            elif target is not None and bar.open >= target:
                self._fill_exit(i, bar, bar.open, "take_profit")     # gapped through target
            elif stop is not None and bar.low <= stop:
                self._fill_exit(i, bar, stop, "stop_loss")           # stop first: worst case
            elif target is not None and bar.high >= target:
                self._fill_exit(i, bar, target, "take_profit")
        else:
            if stop is not None and bar.open >= stop:
                self._fill_exit(i, bar, bar.open, "stop_loss")
            elif target is not None and bar.open <= target:
                self._fill_exit(i, bar, bar.open, "take_profit")
            elif stop is not None and bar.high >= stop:
                self._fill_exit(i, bar, stop, "stop_loss")
            elif target is not None and bar.low <= target:
                self._fill_exit(i, bar, target, "take_profit")

    # --- signals --------------------------------------------------------------------

    def _process_signal(self, i: int, signal: TradeSignal) -> None:
        self._stats["signals_generated"] += 1
        earliest = i + self.cfg.friction.fill_delay_bars
        current_side = self._trade.side if self._trade is not None else None

        if current_side is None:
            # Flat: latest signal wins over any not-yet-filled pending entry.
            self._pending_entry = _PendingEntry(
                side=signal.side,
                signal_index=i,
                earliest_index=earliest,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
            )
        elif signal.side is not current_side:
            self._exit_pending = True
            self._exit_reason = self._exit_reason or "opposite_signal"
            if self.cfg.allow_reverse:
                self._pending_entry = _PendingEntry(
                    side=signal.side,
                    signal_index=i,
                    earliest_index=earliest,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                )
            else:
                self._pending_entry = None
        else:
            self._stats["signals_ignored_same_side"] += 1

    def _signed_open_qty(self) -> float:
        if self._trade is None:
            return 0.0
        qty = self._trade.open_qty
        return qty if self._trade.side is OrderSide.BUY else -qty

    # --- main loop -------------------------------------------------------------------

    def run(self) -> EngineResult:
        bars = self.bars
        lookback = self.cfg.lookback_bars
        last_index = len(bars) - 1

        for i, bar in enumerate(bars):
            # 1) pending market exit (opposite signal / carried remainder)
            if self._trade is not None and self._exit_pending:
                self._fill_exit(i, bar, bar.open, self._exit_reason or "opposite_signal")
            # 2) protective stop/target, intra-bar (skipped while unwinding at market)
            if self._trade is not None and not self._exit_pending:
                self._check_protective_exits(i, bar)
            # Any exit (full or partial) drops a same-side carried entry
            # remainder; a reverse pending entry (remaining_qty None) survives.
            if (
                self._pending_entry is not None
                and self._pending_entry.remaining_qty is not None
                and (self._trade is None or self._exit_pending)
            ):
                self._pending_entry = None
            # 3) entry fills (latency-delayed, in-session only)
            self._try_fill_entry(i, bar)
            # A trade opened at THIS bar's open lives through the rest of the
            # bar, so its stop/target is checked against this same bar too
            # (the open is the bar's first price - temporally valid).
            if (
                self._trade is not None
                and self._trade.entry_index == i
                and not self._exit_pending
            ):
                self._check_protective_exits(i, bar)
            # 4) mark to market at the close
            equity = self._cash + self._signed_open_qty() * bar.close
            self._equity.append(equity)
            self._timestamps.append(bar.timestamp)
            if self._trade is not None and self._trade.open_qty > _EPS:
                self._bars_in_position += 1
            # 5) evaluate the strategy on bars <= i (session-gated)
            if i < last_index:  # a last-bar signal could never fill: skip work
                if self._in_session(bar.timestamp):
                    window = bars[max(0, i + 1 - lookback): i + 1]
                    signal = self.strategy.evaluate(window, market=self.cfg.market)
                    if signal is not None:
                        self._process_signal(i, signal)
                elif self.cfg.sessions:
                    self._stats["signals_skipped_out_of_session"] += 1

        # 6) end of data: force close at the last close (frictions, no cap)
        if self._trade is not None and self._trade.open_qty > _EPS:
            self._fill_exit(last_index, bars[-1], bars[-1].close, "end_of_data", capped=False)
            self._equity[-1] = self._cash  # final mark = post-close cash

        periods = self.cfg.periods_per_year or PERIODS_PER_YEAR_BY_TIMEFRAME.get(
            bars[0].timeframe, 252.0
        )
        pnls = [t["net_pnl"] for t in self._trades]
        metric_values = metrics_mod.summarize(
            self._equity,
            pnls,
            periods_per_year=periods,
            bars_in_position=self._bars_in_position,
            risk_free_rate=self.cfg.risk_free_rate,
        )
        curve = [
            {"timestamp": ts.isoformat(), "equity": eq}
            for ts, eq in zip(self._timestamps, self._equity)
        ]
        return EngineResult(
            equity_curve=curve,
            trades=self._trades,
            metrics=metric_values,
            stats=dict(self._stats),
        )


def run_backtest(
    strategy: SignalSource, bars: list[Bar], config: Optional[BacktestConfig] = None
) -> EngineResult:
    """Convenience wrapper: build an engine and run it."""
    return BacktestEngine(strategy, bars, config).run()
