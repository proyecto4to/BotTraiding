"""Momentum strategies: buy strength, sell weakness."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from trading_contracts import Bar, OrderSide, TradeSignal

from ..categories import StrategyCategory
from ..indicators import atr, is_nan, roc, rsi
from ..plugin import ParameterSpec, StrategyPlugin, atr_exit_specs
from ..registry import register_strategy

_ALL_MARKETS = ("crypto", "forex", "stocks", "futures")


@register_strategy
class RocMomentum(StrategyPlugin):
    """Rate-of-change threshold momentum.

    Edge: once N-bar return crosses a meaningful threshold, autocorrelation
    of returns tends to carry the move further; entering on the fresh cross
    avoids chasing already-extended readings.
    """

    strategy_id = "roc_momentum"
    name = "ROC Momentum"
    category = StrategyCategory.MOMENTUM
    markets = _ALL_MARKETS
    timeframes = ("1h", "4h", "1d")
    param_specs = (
        ParameterSpec(name="roc_period", type="int", default=12, min=2, max=200,
                      description="Rate-of-change lookback."),
        ParameterSpec(name="threshold_pct", type="float", default=2.0, min=0.1, max=50.0,
                      description="Percent ROC that must be crossed to enter."),
        *atr_exit_specs(),
    )

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        if len(bars) < max(p["roc_period"], p["atr_period"]) + 2:
            return None
        r = roc(closes, p["roc_period"])
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        if any(is_nan(x) for x in (r[-2], r[-1], a)):
            return None
        th = p["threshold_pct"]
        if r[-1] > th and r[-2] <= th:
            side = OrderSide.BUY
        elif r[-1] < -th and r[-2] >= -th:
            side = OrderSide.SELL
        else:
            return None
        stop, tp = self._atr_exits(closes[-1], side, a)
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.35, (abs(float(r[-1])) - th) * 0.05),
            stop_loss=stop,
            take_profit=tp,
            metadata={"roc": round(float(r[-1]), 4)},
        )


@register_strategy
class DualMomentum(StrategyPlugin):
    """Dual-horizon absolute momentum (simplified Antonacci).

    Edge: requiring positive momentum on BOTH a fast and a slow horizon
    filters counter-trend noise; the classic cross-asset relative leg needs
    a universe feed and is deferred to the ai/portfolio layer.
    """

    strategy_id = "dual_momentum"
    name = "Dual Momentum"
    category = StrategyCategory.MOMENTUM
    markets = _ALL_MARKETS
    timeframes = ("4h", "1d")
    param_specs = (
        ParameterSpec(name="fast_lookback", type="int", default=20, min=2, max=200,
                      description="Fast momentum horizon."),
        ParameterSpec(name="slow_lookback", type="int", default=60, min=5, max=400,
                      description="Slow momentum horizon."),
        *atr_exit_specs(),
    )

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> list[str]:
        if params["fast_lookback"] >= params["slow_lookback"]:
            return ["'fast_lookback' must be < 'slow_lookback'"]
        return []

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        if len(bars) < max(p["slow_lookback"], p["atr_period"]) + 2:
            return None
        rf = roc(closes, p["fast_lookback"])
        rs = roc(closes, p["slow_lookback"])
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        if any(is_nan(x) for x in (rf[-2], rs[-2], rf[-1], rs[-1], a)):
            return None
        long_now = rf[-1] > 0.0 and rs[-1] > 0.0
        long_prev = rf[-2] > 0.0 and rs[-2] > 0.0
        short_now = rf[-1] < 0.0 and rs[-1] < 0.0
        short_prev = rf[-2] < 0.0 and rs[-2] < 0.0
        if long_now and not long_prev:
            side = OrderSide.BUY
        elif short_now and not short_prev:
            side = OrderSide.SELL
        else:
            return None
        stop, tp = self._atr_exits(closes[-1], side, a)
        strength = (abs(float(rf[-1])) + abs(float(rs[-1]))) * 0.02
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.3, strength),
            stop_loss=stop,
            take_profit=tp,
            metadata={"roc_fast": round(float(rf[-1]), 4), "roc_slow": round(float(rs[-1]), 4)},
        )


@register_strategy
class MomentumRanking(StrategyPlugin):
    """Time-series momentum percentile ranking.

    Edge: momentum that ranks in the top decile of its own recent history
    identifies unusually strong impulses that tend to continue. The
    cross-sectional (multi-symbol) variant needs a universe feed and lives
    with the ai-engine ranking layer; this is the single-symbol analogue.
    """

    strategy_id = "momentum_ranking"
    name = "Momentum Percentile Ranking"
    category = StrategyCategory.MOMENTUM
    markets = _ALL_MARKETS
    timeframes = ("4h", "1d")
    param_specs = (
        ParameterSpec(name="roc_period", type="int", default=12, min=2, max=100,
                      description="Momentum (ROC) lookback."),
        ParameterSpec(name="rank_window", type="int", default=60, min=10, max=400,
                      description="History window the current ROC is ranked against."),
        ParameterSpec(name="percentile_entry", type="float", default=90.0, min=50.0, max=99.0,
                      description="Percentile the ROC must exceed (or mirror for sells)."),
        *atr_exit_specs(),
    )

    @staticmethod
    def _pct_rank(window: np.ndarray) -> float:
        """Percentile of window[-1] among the earlier values of the window."""
        current, others = window[-1], window[:-1]
        if len(others) == 0:
            return 0.0
        return float((others < current).sum()) / len(others) * 100.0

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        need = p["roc_period"] + p["rank_window"] + 2
        if len(bars) < max(need, p["atr_period"] + 2):
            return None
        r = roc(closes, p["roc_period"])
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        window = r[-p["rank_window"]:]
        prev_window = r[-p["rank_window"] - 1 : -1]
        if is_nan(a) or np.isnan(window).any() or np.isnan(prev_window).any():
            return None
        pe = p["percentile_entry"]
        pct_now = self._pct_rank(window)
        pct_prev = self._pct_rank(prev_window)
        long_now = r[-1] > 0.0 and pct_now > pe
        long_prev = r[-2] > 0.0 and pct_prev > pe
        short_now = r[-1] < 0.0 and pct_now < (100.0 - pe)
        short_prev = r[-2] < 0.0 and pct_prev < (100.0 - pe)
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
            confidence=0.55 + min(0.3, abs(pct_now - 50.0) / 200.0),
            stop_loss=stop,
            take_profit=tp,
            metadata={"roc": round(float(r[-1]), 4), "percentile": round(pct_now, 2)},
        )


@register_strategy
class RsiDivergence(StrategyPlugin):
    """Simplified RSI divergence.

    Edge: when price prints a lower low but RSI prints a higher low,
    downside momentum is exhausting while sellers still control the tape -
    a classic reversal precondition. Entry waits for the first up-turn bar
    to avoid catching the falling knife. (Pivot detection is windowed
    argmin/argmax - intentionally simple and deterministic.)
    """

    strategy_id = "rsi_divergence"
    name = "RSI Divergence"
    category = StrategyCategory.MOMENTUM
    markets = _ALL_MARKETS
    timeframes = ("1h", "4h", "1d")
    param_specs = (
        ParameterSpec(name="rsi_period", type="int", default=14, min=2, max=50,
                      description="RSI lookback."),
        ParameterSpec(name="lookback", type="int", default=40, min=10, max=200,
                      description="Window scanned for the two pivots."),
        ParameterSpec(name="min_rsi_delta", type="float", default=5.0, min=0.0, max=50.0,
                      description="Minimum RSI improvement between the pivots."),
        *atr_exit_specs(),
    )

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        n = len(closes)
        if n < p["lookback"] + p["rsi_period"] + 1 or n < p["atr_period"] + 2:
            return None
        r = rsi(closes, p["rsi_period"])
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        if is_nan(a):
            return None
        start = n - p["lookback"]
        half = p["lookback"] // 2
        seg1 = range(start, n - half)
        seg2 = range(n - half, n)
        window_vals = [r[i] for i in range(start, n)]
        if any(is_nan(x) for x in window_vals):
            return None
        c = closes
        delta = p["min_rsi_delta"]
        turn_up = c[-1] > c[-2] and c[-2] <= c[-3]
        turn_dn = c[-1] < c[-2] and c[-2] >= c[-3]
        side = None
        if turn_up:
            i1 = min(seg1, key=lambda i: c[i])
            i2 = min(seg2, key=lambda i: c[i])
            if i2 < n - 1 and c[i2] < c[i1] and r[i2] >= r[i1] + delta:
                side, pivots = OrderSide.BUY, (i1, i2)
        if side is None and turn_dn:
            j1 = max(seg1, key=lambda i: c[i])
            j2 = max(seg2, key=lambda i: c[i])
            if j2 < n - 1 and c[j2] > c[j1] and r[j2] <= r[j1] - delta:
                side, pivots = OrderSide.SELL, (j1, j2)
        if side is None:
            return None
        stop, tp = self._atr_exits(c[-1], side, a)
        i1, i2 = pivots
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.3, abs(float(r[i2]) - float(r[i1])) / 100.0),
            stop_loss=stop,
            take_profit=tp,
            metadata={
                "pivot_rsi_first": round(float(r[i1]), 4),
                "pivot_rsi_second": round(float(r[i2]), 4),
            },
        )
