"""Trend-following strategies: ride established directional moves."""

from __future__ import annotations

from typing import Any, Optional

from trading_contracts import Bar, OrderSide, TradeSignal

from ..categories import StrategyCategory
from ..indicators import atr, ema, is_nan, macd, sma
from ..plugin import ParameterSpec, StrategyPlugin, atr_exit_specs
from ..registry import register_strategy

_ALL_MARKETS = ("crypto", "forex", "stocks", "futures")
_SWING_TFS = ("15m", "1h", "4h", "1d")


def _crossover_specs(fast: int, slow: int) -> tuple[ParameterSpec, ...]:
    return (
        ParameterSpec(
            name="fast_period",
            type="int",
            default=fast,
            min=2,
            max=200,
            description="Fast moving-average lookback.",
        ),
        ParameterSpec(
            name="slow_period",
            type="int",
            default=slow,
            min=3,
            max=400,
            description="Slow moving-average lookback.",
        ),
        *atr_exit_specs(),
    )


class _MaCrossoverBase(StrategyPlugin):
    """Shared crossover logic; subclasses choose the averaging function."""

    category = StrategyCategory.TREND
    markets = _ALL_MARKETS
    timeframes = _SWING_TFS

    @staticmethod
    def _ma(closes: list[float], period: int):  # pragma: no cover - abstract
        raise NotImplementedError

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> list[str]:
        if params["fast_period"] >= params["slow_period"]:
            return ["'fast_period' must be < 'slow_period'"]
        return []

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        need = max(p["slow_period"], p["atr_period"]) + 2
        if len(bars) < need:
            return None
        fast = self._ma(closes, p["fast_period"])
        slow = self._ma(closes, p["slow_period"])
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        if any(is_nan(x) for x in (fast[-2], slow[-2], fast[-1], slow[-1], a)):
            return None
        cross_up = fast[-2] <= slow[-2] and fast[-1] > slow[-1]
        cross_dn = fast[-2] >= slow[-2] and fast[-1] < slow[-1]
        if not (cross_up or cross_dn):
            return None
        side = OrderSide.BUY if cross_up else OrderSide.SELL
        stop, tp = self._atr_exits(closes[-1], side, a)
        spread = abs(fast[-1] - slow[-1]) / a if a > 0 else 0.0
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.35, spread * 0.2),
            stop_loss=stop,
            take_profit=tp,
            metadata={"fast": round(float(fast[-1]), 6), "slow": round(float(slow[-1]), 6)},
        )


@register_strategy
class SmaCrossover(_MaCrossoverBase):
    """Simple moving average crossover.

    Edge: medium-term trends persist; entering when the fast SMA crosses
    the slow SMA captures the meat of a move while the ATR stop bounds the
    cost of whipsaws in ranging markets.
    """

    strategy_id = "sma_crossover"
    name = "SMA Crossover"
    param_specs = _crossover_specs(fast=10, slow=30)

    @staticmethod
    def _ma(closes: list[float], period: int):
        return sma(closes, period)


@register_strategy
class EmaCrossover(_MaCrossoverBase):
    """Exponential moving average crossover.

    Edge: same trend-persistence edge as the SMA cross but the EMA's
    recency weighting reacts faster after sharp reversals, reducing lag at
    the cost of slightly more whipsaw.
    """

    strategy_id = "ema_crossover"
    name = "EMA Crossover"
    param_specs = _crossover_specs(fast=12, slow=26)

    @staticmethod
    def _ma(closes: list[float], period: int):
        return ema(closes, period)


@register_strategy
class MacdTrend(StrategyPlugin):
    """MACD line / signal line crossover trend entry.

    Edge: the MACD histogram turning through zero marks acceleration of a
    new trend leg; entering on the line/signal cross rides momentum shifts
    earlier than a plain MA cross while filtering single-bar noise.
    """

    strategy_id = "macd_trend"
    name = "MACD Trend"
    category = StrategyCategory.TREND
    markets = _ALL_MARKETS
    timeframes = _SWING_TFS
    param_specs = (
        ParameterSpec(name="fast_period", type="int", default=12, min=2, max=100,
                      description="Fast EMA lookback."),
        ParameterSpec(name="slow_period", type="int", default=26, min=3, max=200,
                      description="Slow EMA lookback."),
        ParameterSpec(name="signal_period", type="int", default=9, min=2, max=100,
                      description="Signal line EMA lookback."),
        *atr_exit_specs(),
    )

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> list[str]:
        if params["fast_period"] >= params["slow_period"]:
            return ["'fast_period' must be < 'slow_period'"]
        return []

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        need = p["slow_period"] + p["signal_period"] + max(2, p["atr_period"])
        if len(bars) < need:
            return None
        line, sig, hist = macd(
            closes, p["fast_period"], p["slow_period"], p["signal_period"]
        )
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        if any(is_nan(x) for x in (line[-2], sig[-2], line[-1], sig[-1], a)):
            return None
        cross_up = line[-2] <= sig[-2] and line[-1] > sig[-1]
        cross_dn = line[-2] >= sig[-2] and line[-1] < sig[-1]
        if not (cross_up or cross_dn):
            return None
        side = OrderSide.BUY if cross_up else OrderSide.SELL
        stop, tp = self._atr_exits(closes[-1], side, a)
        strength = abs(hist[-1]) / a if a > 0 else 0.0
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.35, strength),
            stop_loss=stop,
            take_profit=tp,
            metadata={"macd": round(float(line[-1]), 6), "signal": round(float(sig[-1]), 6)},
        )
