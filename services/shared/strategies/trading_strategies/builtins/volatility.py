"""Volatility strategies: trade the volatility cycle itself."""

from __future__ import annotations

from typing import Any, Optional

from trading_contracts import Bar, OrderSide, TradeSignal

from ..categories import StrategyCategory
from ..indicators import atr, bollinger, is_nan, keltner, sma
from ..plugin import ParameterSpec, StrategyPlugin, atr_exit_specs
from ..registry import register_strategy

_ALL_MARKETS = ("crypto", "forex", "stocks", "futures")


@register_strategy
class KeltnerSqueeze(StrategyPlugin):
    """Bollinger-inside-Keltner squeeze release (TTM-squeeze style).

    Edge: volatility is cyclical - when Bollinger bands compress inside the
    Keltner channel, energy is coiling; the first bar where the bands
    escape marks the regime flip from contraction to expansion, and the
    move usually continues in the direction of prevailing momentum.
    """

    strategy_id = "keltner_squeeze"
    name = "Keltner Squeeze Release"
    category = StrategyCategory.VOLATILITY
    markets = _ALL_MARKETS
    timeframes = ("15m", "1h", "4h", "1d")
    param_specs = (
        ParameterSpec(name="bb_period", type="int", default=20, min=5, max=200,
                      description="Bollinger band lookback."),
        ParameterSpec(name="bb_std", type="float", default=2.0, min=0.5, max=5.0,
                      description="Bollinger width in standard deviations."),
        ParameterSpec(name="kc_period", type="int", default=20, min=5, max=200,
                      description="Keltner channel lookback."),
        ParameterSpec(name="kc_mult", type="float", default=1.5, min=0.5, max=5.0,
                      description="Keltner half-width in ATR multiples."),
        ParameterSpec(name="momentum_period", type="int", default=12, min=2, max=100,
                      description="Lookback for the direction filter."),
        *atr_exit_specs(),
    )

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        need = max(p["bb_period"], p["kc_period"], p["momentum_period"], p["atr_period"]) + 2
        if len(bars) < need:
            return None
        highs, lows = self._highs(bars), self._lows(bars)
        _, b_up, b_lo = bollinger(closes, p["bb_period"], p["bb_std"])
        _, k_up, k_lo = keltner(highs, lows, closes, p["kc_period"], p["kc_mult"])
        a = atr(highs, lows, closes, p["atr_period"])[-1]
        if any(is_nan(x) for x in (b_up[-2], b_lo[-2], k_up[-2], k_lo[-2],
                                   b_up[-1], b_lo[-1], k_up[-1], k_lo[-1], a)):
            return None
        squeeze_prev = b_up[-2] < k_up[-2] and b_lo[-2] > k_lo[-2]
        squeeze_now = b_up[-1] < k_up[-1] and b_lo[-1] > k_lo[-1]
        if not (squeeze_prev and not squeeze_now):
            return None
        mom_ma = sma(closes, p["momentum_period"])[-1]
        if is_nan(mom_ma):
            return None
        mom = closes[-1] - float(mom_ma)
        if mom > 0.0:
            side = OrderSide.BUY
        elif mom < 0.0:
            side = OrderSide.SELL
        else:
            return None
        stop, tp = self._atr_exits(closes[-1], side, a)
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.3, abs(mom) / a if a > 0 else 0.0),
            stop_loss=stop,
            take_profit=tp,
            metadata={"momentum": round(mom, 6)},
        )


@register_strategy
class VolatilityRegime(StrategyPlugin):
    """Volatility-regime-filtered trend continuation.

    Edge: trends persist far better in quiet regimes; when short-horizon
    ATR compresses below a fraction of long-horizon ATR, continuation
    entries in the direction of the moving-average trend carry better odds
    than in high-volatility chop, where this strategy stays flat (acting
    as its own regime filter).
    """

    strategy_id = "volatility_regime"
    name = "Volatility Regime Filter"
    category = StrategyCategory.VOLATILITY
    markets = _ALL_MARKETS
    timeframes = ("1h", "4h", "1d")
    param_specs = (
        ParameterSpec(name="atr_fast", type="int", default=10, min=2, max=100,
                      description="Short-horizon ATR lookback."),
        ParameterSpec(name="atr_slow", type="int", default=50, min=5, max=400,
                      description="Long-horizon ATR lookback."),
        ParameterSpec(name="max_ratio", type="float", default=0.85, min=0.1, max=2.0,
                      description="fast/slow ATR ratio below which the regime is quiet."),
        ParameterSpec(name="trend_period", type="int", default=20, min=5, max=200,
                      description="Moving-average trend lookback."),
        *atr_exit_specs(),
    )

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> list[str]:
        if params["atr_fast"] >= params["atr_slow"]:
            return ["'atr_fast' must be < 'atr_slow'"]
        return []

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        if len(bars) < max(p["atr_slow"], p["trend_period"], p["atr_period"]) + 2:
            return None
        highs, lows = self._highs(bars), self._lows(bars)
        af = atr(highs, lows, closes, p["atr_fast"])
        aslow = atr(highs, lows, closes, p["atr_slow"])
        trend = sma(closes, p["trend_period"])
        a = atr(highs, lows, closes, p["atr_period"])[-1]
        if any(is_nan(x) for x in (af[-2], af[-1], aslow[-2], aslow[-1],
                                   trend[-2], trend[-1], a)):
            return None
        if not (aslow[-1] > 0.0 and aslow[-2] > 0.0):
            return None
        ratio_now = float(af[-1] / aslow[-1])
        ratio_prev = float(af[-2] / aslow[-2])
        quiet_now = ratio_now < p["max_ratio"]
        quiet_prev = ratio_prev < p["max_ratio"]
        long_now = quiet_now and closes[-1] > trend[-1]
        long_prev = quiet_prev and closes[-2] > trend[-2]
        short_now = quiet_now and closes[-1] < trend[-1]
        short_prev = quiet_prev and closes[-2] < trend[-2]
        if long_now and not long_prev:
            side = OrderSide.BUY
        elif short_now and not short_prev:
            side = OrderSide.SELL
        else:
            return None
        stop, tp = self._atr_exits(closes[-1], side, a)
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.3, p["max_ratio"] - ratio_now),
            stop_loss=stop,
            take_profit=tp,
            metadata={"atr_ratio": round(ratio_now, 4)},
        )
