"""Breakout strategies: trade fresh escapes from consolidation ranges."""

from __future__ import annotations

from typing import Optional

from trading_contracts import Bar, OrderSide, TradeSignal

from ..categories import StrategyCategory
from ..indicators import atr, donchian, is_nan, sma
from ..plugin import ParameterSpec, StrategyPlugin, atr_exit_specs
from ..registry import register_strategy

_ALL_MARKETS = ("crypto", "forex", "stocks", "futures")


@register_strategy
class DonchianBreakout(StrategyPlugin):
    """Donchian channel breakout (turtle-style).

    Edge: a close beyond the N-bar extreme means every position opened in
    the window is (at best) break-even on one side - forced covering and
    stop cascades tend to extend the move. The prior bar's channel is used
    so the breakout bar itself cannot widen its own trigger.
    """

    strategy_id = "donchian_breakout"
    name = "Donchian Breakout"
    category = StrategyCategory.BREAKOUT
    markets = _ALL_MARKETS
    timeframes = ("1h", "4h", "1d")
    param_specs = (
        ParameterSpec(name="channel_period", type="int", default=20, min=5, max=200,
                      description="Donchian channel lookback."),
        *atr_exit_specs(),
    )

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        if len(bars) < max(p["channel_period"], p["atr_period"]) + 2:
            return None
        upper, lower = donchian(self._highs(bars), self._lows(bars), p["channel_period"])
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])[-1]
        if any(is_nan(x) for x in (upper[-2], lower[-2], a)):
            return None
        close = closes[-1]
        if close > upper[-2]:
            side, edge = OrderSide.BUY, (close - upper[-2]) / a if a > 0 else 0.0
        elif close < lower[-2]:
            side, edge = OrderSide.SELL, (lower[-2] - close) / a if a > 0 else 0.0
        else:
            return None
        stop, tp = self._atr_exits(close, side, a)
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.35, float(edge) * 0.3),
            stop_loss=stop,
            take_profit=tp,
            metadata={
                "channel_high": round(float(upper[-2]), 6),
                "channel_low": round(float(lower[-2]), 6),
            },
        )


@register_strategy
class AtrChannelBreakout(StrategyPlugin):
    """ATR (volatility) channel breakout around a moving average.

    Edge: a close more than k ATRs from its own mean is a statistically
    outsized move for the CURRENT volatility regime, unlike fixed-percent
    channels; fresh escapes signal initiative buying/selling. Only the
    first bar outside the channel fires, avoiding re-entry spam.
    """

    strategy_id = "atr_channel_breakout"
    name = "ATR Channel Breakout"
    category = StrategyCategory.BREAKOUT
    markets = _ALL_MARKETS
    timeframes = ("15m", "1h", "4h", "1d")
    param_specs = (
        ParameterSpec(name="ma_period", type="int", default=20, min=5, max=200,
                      description="Moving-average midline lookback."),
        ParameterSpec(name="channel_mult", type="float", default=2.0, min=0.5, max=6.0,
                      description="Channel half-width in ATR multiples."),
        *atr_exit_specs(),
    )

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        closes = self._closes(bars)
        if len(bars) < max(p["ma_period"], p["atr_period"]) + 2:
            return None
        mid = sma(closes, p["ma_period"])
        a = atr(self._highs(bars), self._lows(bars), closes, p["atr_period"])
        if any(is_nan(x) for x in (mid[-2], mid[-1], a[-2], a[-1])):
            return None
        k = p["channel_mult"]
        up_now, up_prev = mid[-1] + k * a[-1], mid[-2] + k * a[-2]
        dn_now, dn_prev = mid[-1] - k * a[-1], mid[-2] - k * a[-2]
        c_now, c_prev = closes[-1], closes[-2]
        if c_now > up_now and c_prev <= up_prev:
            side = OrderSide.BUY
        elif c_now < dn_now and c_prev >= dn_prev:
            side = OrderSide.SELL
        else:
            return None
        stop, tp = self._atr_exits(c_now, side, a[-1])
        dist = abs(c_now - float(mid[-1])) / a[-1] if a[-1] > 0 else 0.0
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.35, (dist - k) * 0.3),
            stop_loss=stop,
            take_profit=tp,
            metadata={"midline": round(float(mid[-1]), 6), "atr": round(float(a[-1]), 6)},
        )


@register_strategy
class OpeningRangeBreakout(StrategyPlugin):
    """Opening range breakout (intraday).

    Edge: the first bars of a session encode the overnight order imbalance;
    a break of that range in either direction tends to set the day's
    direction. The opposite side of the range is the natural stop, giving a
    structurally defined risk unit.
    """

    strategy_id = "opening_range_breakout"
    name = "Opening Range Breakout"
    category = StrategyCategory.BREAKOUT
    markets = ("crypto", "stocks", "futures")
    timeframes = ("1m", "5m", "15m")
    param_specs = (
        ParameterSpec(name="range_bars", type="int", default=6, min=1, max=100,
                      description="Bars that define the opening range."),
        ParameterSpec(name="risk_reward", type="float", default=2.0, min=0.5, max=10.0,
                      description="Take-profit as a multiple of range risk."),
    )

    def _evaluate(self, bars: list[Bar]) -> Optional[TradeSignal]:
        p = self.params
        day = bars[-1].timestamp.date()
        session = [b for b in bars if b.timestamp.date() == day]
        if len(session) < p["range_bars"] + 2:
            return None
        opening = session[: p["range_bars"]]
        range_high = max(b.high for b in opening)
        range_low = min(b.low for b in opening)
        if not (range_high > range_low):
            return None
        close, prev_close = session[-1].close, session[-2].close
        rr = p["risk_reward"]
        if close > range_high and prev_close <= range_high:
            side, stop = OrderSide.BUY, range_low
            tp = close + rr * (close - range_low)
            edge = (close - range_high) / (range_high - range_low)
        elif close < range_low and prev_close >= range_low:
            side, stop = OrderSide.SELL, range_high
            tp = close - rr * (range_high - close)
            edge = (range_low - close) / (range_high - range_low)
        else:
            return None
        return self._signal(
            bars,
            side,
            confidence=0.55 + min(0.35, edge),
            stop_loss=stop,
            take_profit=tp,
            metadata={"range_high": range_high, "range_low": range_low},
        )
