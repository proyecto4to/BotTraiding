"""Mean-reversion strategies: fade statistically stretched moves."""

from __future__ import annotations

from typing import Any, Optional

from trading_contracts import Bar, OrderSide, TradeSignal

from ..categories import StrategyCategory
from ..indicators import atr, bollinger, is_nan, rsi, session_vwap, sma, zscore
from ..plugin import ParameterSpec, StrategyPlugin, atr_exit_specs
from ..registry import register_strategy

_ALL_MARKETS = ("crypto", "forex", "stocks", "futures")


@register_strategy
class BollingerReversion(StrategyPlugin):
    """Bollinger band mean reversion.

    Edge: closes beyond +/- N standard deviations are statistically
    stretched; absent a regime change, price tends to snap back toward the
    middle band, which doubles as the take-profit anchor.
    """

    strategy_id = "bollinger_reversion"
    name = "Bollinger Mean Reversion"
    category = StrategyCategory.MEAN_REVERSION
    markets = _ALL_MARKETS
    timeframes = ("5m", "15m", "1h", "4h", "1d")
    param_specs = (
        ParameterSpec(name="bb_period", type="int", default=20, min=5, max=200,
                      description="Bollinger band lookback."),
        ParameterSpec(name="num_std", type="float", default=2.0, min=0.5, max=5.0,
                      description="Band width in standard deviations."),
        *atr_exit_specs(),
    )

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        if len(bars) < max(p["bb_period"], p["atr_period"]) + 2:
            return None
        mid, upper, lower = bollinger(closes, p["bb_period"], p["num_std"])
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        if any(is_nan(x) for x in (mid[-1], upper[-1], lower[-1], a)):
            return None
        if not (upper[-1] - lower[-1] > 0.0):
            return None
        close = closes[-1]
        mult = p["stop_atr_mult"]
        if close < lower[-1]:
            side, stop, tp = OrderSide.BUY, close - mult * a, float(mid[-1])
            depth = (lower[-1] - close) / a if a > 0 else 0.0
        elif close > upper[-1]:
            side, stop, tp = OrderSide.SELL, close + mult * a, float(mid[-1])
            depth = (close - upper[-1]) / a if a > 0 else 0.0
        else:
            return None
        return self._signal(
            bars,
            side,
            confidence=0.5 + min(0.4, depth * 0.4),
            stop_loss=stop,
            take_profit=tp,
            metadata={"middle_band": round(float(mid[-1]), 6)},
        )


@register_strategy
class Rsi2Reversion(StrategyPlugin):
    """Connors-style RSI(2) extreme reversion.

    Edge: a 2-period RSI below ~10 marks capitulation-grade short-term
    selling that historically mean-reverts within a few bars; an optional
    long-term SMA filter keeps entries aligned with the larger trend.
    """

    strategy_id = "rsi2_reversion"
    name = "RSI(2) Reversion"
    category = StrategyCategory.MEAN_REVERSION
    markets = _ALL_MARKETS
    timeframes = ("1h", "4h", "1d")
    param_specs = (
        ParameterSpec(name="rsi_period", type="int", default=2, min=2, max=14,
                      description="RSI lookback (2 = classic Connors)."),
        ParameterSpec(name="buy_threshold", type="float", default=10.0, min=1.0, max=50.0,
                      description="RSI below this proposes a buy."),
        ParameterSpec(name="sell_threshold", type="float", default=90.0, min=50.0, max=99.0,
                      description="RSI above this proposes a sell."),
        ParameterSpec(name="trend_filter_period", type="int", default=0, min=0, max=400,
                      description="SMA trend filter lookback; 0 disables it."),
        *atr_exit_specs(),
    )

    @classmethod
    def check_params(cls, params: dict[str, Any]) -> list[str]:
        if params["buy_threshold"] >= params["sell_threshold"]:
            return ["'buy_threshold' must be < 'sell_threshold'"]
        return []

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        need = max(p["rsi_period"] + 1, p["atr_period"] + 1, p["trend_filter_period"]) + 1
        if len(bars) < need:
            return None
        r = rsi(closes, p["rsi_period"])[-1]
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        if is_nan(r) or is_nan(a):
            return None
        trend_up = trend_dn = True
        if p["trend_filter_period"] > 0:
            s = sma(closes, p["trend_filter_period"])[-1]
            if is_nan(s):
                return None
            trend_up, trend_dn = closes[-1] > s, closes[-1] < s
        if r < p["buy_threshold"] and trend_up:
            side = OrderSide.BUY
            edge = (p["buy_threshold"] - r) / max(p["buy_threshold"], 1.0)
        elif r > p["sell_threshold"] and trend_dn:
            side = OrderSide.SELL
            edge = (r - p["sell_threshold"]) / max(100.0 - p["sell_threshold"], 1.0)
        else:
            return None
        stop, tp = self._atr_exits(closes[-1], side, a)
        return self._signal(
            bars,
            side,
            confidence=0.5 + min(0.4, edge * 0.4),
            stop_loss=stop,
            take_profit=tp,
            metadata={"rsi": round(float(r), 4)},
        )


@register_strategy
class ZScoreReversion(StrategyPlugin):
    """Rolling z-score reversion to the mean.

    Edge: when the close sits more than ``entry_z`` standard deviations
    from its rolling mean, the expected value of a reversion toward that
    mean (the take-profit) exceeds the ATR-bounded risk of continuation.
    """

    strategy_id = "zscore_reversion"
    name = "Z-Score Reversion"
    category = StrategyCategory.MEAN_REVERSION
    markets = _ALL_MARKETS
    timeframes = ("15m", "1h", "4h", "1d")
    param_specs = (
        ParameterSpec(name="lookback", type="int", default=20, min=5, max=200,
                      description="Rolling mean/std lookback."),
        ParameterSpec(name="entry_z", type="float", default=2.0, min=0.5, max=5.0,
                      description="Absolute z-score required to enter."),
        *atr_exit_specs(),
    )

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        if len(bars) < max(p["lookback"], p["atr_period"]) + 2:
            return None
        z = zscore(closes, p["lookback"])[-1]
        mean = sma(closes, p["lookback"])[-1]
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        if any(is_nan(x) for x in (z, mean, a)):
            return None
        mult = p["stop_atr_mult"]
        close = closes[-1]
        if z < -p["entry_z"]:
            side, stop, tp = OrderSide.BUY, close - mult * a, float(mean)
        elif z > p["entry_z"]:
            side, stop, tp = OrderSide.SELL, close + mult * a, float(mean)
        else:
            return None
        return self._signal(
            bars,
            side,
            confidence=0.5 + min(0.4, (abs(float(z)) - p["entry_z"]) * 0.15),
            stop_loss=stop,
            take_profit=tp,
            metadata={"zscore": round(float(z), 4)},
        )


@register_strategy
class VwapReversion(StrategyPlugin):
    """Intraday reversion to the session VWAP.

    Edge: VWAP is the institutional fair-value anchor of the session;
    extensions beyond a percent threshold tend to get faded back to it by
    execution algos, making VWAP itself the natural take-profit.
    """

    strategy_id = "vwap_reversion"
    name = "VWAP Reversion"
    category = StrategyCategory.MEAN_REVERSION
    markets = ("crypto", "stocks", "futures")
    timeframes = ("1m", "5m", "15m")
    param_specs = (
        ParameterSpec(name="deviation_pct", type="float", default=1.0, min=0.1, max=10.0,
                      description="Percent stretch from VWAP required to enter."),
        ParameterSpec(name="stop_pct", type="float", default=1.5, min=0.1, max=20.0,
                      description="Stop distance in percent of entry price."),
        ParameterSpec(name="min_session_bars", type="int", default=5, min=2, max=200,
                      description="Bars required in the session before trading."),
    )

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        day = bars[-1].timestamp.date()
        session = [b for b in bars if b.timestamp.date() == day]
        if len(session) < p["min_session_bars"]:
            return None
        vw = session_vwap(
            self._highs(session), self._lows(session),
            self._closes(session), self._volumes(session),
        )[-1]
        if is_nan(vw) or vw <= 0.0:
            return None
        close = session[-1].close
        dev_pct = (close - vw) / vw * 100.0
        if dev_pct < -p["deviation_pct"]:
            side = OrderSide.BUY
            stop = close * (1.0 - p["stop_pct"] / 100.0)
        elif dev_pct > p["deviation_pct"]:
            side = OrderSide.SELL
            stop = close * (1.0 + p["stop_pct"] / 100.0)
        else:
            return None
        return self._signal(
            bars,
            side,
            confidence=0.5 + min(0.4, (abs(dev_pct) - p["deviation_pct"]) * 0.1),
            stop_loss=stop,
            take_profit=float(vw),
            metadata={"vwap": round(float(vw), 6), "deviation_pct": round(dev_pct, 4)},
        )
