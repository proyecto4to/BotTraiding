"""Deterministic synthetic bar fixtures that trigger each strategy's edge."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from trading_contracts import Bar

UTC = timezone.utc
DEFAULT_START = datetime(2026, 1, 5, tzinfo=UTC)


def make_bars(
    closes: Sequence[float],
    highs: Optional[Sequence[float]] = None,
    lows: Optional[Sequence[float]] = None,
    volumes: Optional[Sequence[float]] = None,
    symbol: str = "TEST",
    timeframe: str = "1h",
    start: Optional[datetime] = None,
    step: Optional[timedelta] = None,
) -> list[Bar]:
    start = start or DEFAULT_START
    step = step or timedelta(hours=1)
    bars: list[Bar] = []
    prev_close = closes[0]
    for i, close in enumerate(closes):
        high = highs[i] if highs is not None else max(prev_close, close) + 0.5
        low = lows[i] if lows is not None else min(prev_close, close) - 0.5
        volume = volumes[i] if volumes is not None else 1000.0
        bars.append(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                open=prev_close,
                high=high,
                low=low,
                close=close,
                volume=volume,
                timestamp=start + i * step,
            )
        )
        prev_close = close
    return bars


# --- price paths -------------------------------------------------------------


def trend_up_bars() -> list[Bar]:
    """70 bars grinding down (accelerating), then 60 bars rallying hard.

    The slight curvature in the first leg keeps trailing indicators (e.g.
    the MACD signal line) genuinely separated from their base series; a
    perfectly linear leg collapses them onto the same value and turns the
    crossover into float noise.
    """
    down = [100.0 - 0.15 * i - 0.002 * i * i for i in range(70)]
    up = [down[-1] + 0.6 * (i + 1) for i in range(60)]
    return make_bars(down + up)


def trend_down_bars() -> list[Bar]:
    """70 bars grinding up (accelerating), then 60 bars selling off hard."""
    up = [100.0 + 0.15 * i + 0.002 * i * i for i in range(70)]
    down = [up[-1] - 0.6 * (i + 1) for i in range(60)]
    return make_bars(up + down)


def flat_bars(n: int = 140) -> list[Bar]:
    return make_bars([100.0] * n)


def oversold_bars() -> list[Bar]:
    """Quiet oscillation, then a capitulation-grade drop."""
    warm = [100.0 + (0.4 if i % 2 == 0 else -0.4) for i in range(40)]
    drop = [warm[-1] - 1.5 * (i + 1) for i in range(8)]
    return make_bars(warm + drop)


def overbought_bars() -> list[Bar]:
    """Quiet oscillation, then a vertical melt-up."""
    warm = [100.0 + (0.4 if i % 2 == 0 else -0.4) for i in range(40)]
    rise = [warm[-1] + 1.5 * (i + 1) for i in range(8)]
    return make_bars(warm + rise)


def squeeze_bars() -> list[Bar]:
    """Tight coil (Bollinger inside Keltner), then an upside expansion."""
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    for i in range(40):
        c = 100.0 + (0.1 if i % 2 == 0 else -0.1)
        closes.append(c)
        highs.append(c + 0.15)
        lows.append(c - 0.15)
    for c in (100.5, 101.2, 102.0, 102.8, 103.6):
        closes.append(c)
        highs.append(c + 0.5)
        lows.append(c - 0.5)
    return make_bars(closes, highs, lows)


def vol_regime_bars() -> list[Bar]:
    """High-volatility chop, then a quiet steady uptrend."""
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    for i in range(60):
        c = 100.0 + (3.0 if i % 2 == 0 else -3.0)
        closes.append(c)
        highs.append(c + 3.0)
        lows.append(c - 3.0)
    base = closes[-1]
    for j in range(60):
        c = base + 0.3 * (j + 1)
        closes.append(c)
        highs.append(c + 0.3)
        lows.append(c - 0.3)
    return make_bars(closes, highs, lows)


def divergence_bars() -> list[Bar]:
    """Steep first low, rally, shallow lower low (bullish RSI divergence)."""
    closes = [100.0 + (0.2 if i % 2 == 0 else -0.2) for i in range(20)]
    c = closes[-1]
    for _ in range(5):  # steep drop -> momentum low
        c -= 1.2
        closes.append(c)
    for _ in range(10):  # relief rally
        c += 0.5
        closes.append(c)
    for _ in range(12):  # shallow drop -> lower price low, higher RSI low
        c -= 0.45
        closes.append(c)
    for _ in range(2):  # turn-up confirmation
        c += 0.5
        closes.append(c)
    return make_bars(closes)


def vwap_bars() -> list[Bar]:
    """One intraday session hovering at VWAP, then stretching far below it."""
    warm = [100.0 + (0.2 if i % 2 == 0 else -0.2) for i in range(40)]
    drop = [warm[-1] - 0.8 * (i + 1) for i in range(6)]
    return make_bars(
        warm + drop,
        timeframe="5m",
        start=datetime(2026, 1, 6, 9, 30, tzinfo=UTC),
        step=timedelta(minutes=5),
    )


def orb_bars() -> list[Bar]:
    """Prior session + a new session: tight opening range, then a break up."""
    prev_day = make_bars(
        [98.0 + (0.2 if i % 2 == 0 else -0.2) for i in range(10)],
        timeframe="5m",
        start=datetime(2026, 1, 5, 14, 0, tzinfo=UTC),
        step=timedelta(minutes=5),
    )
    range_closes = [100.1, 99.9, 100.2, 99.8, 100.0, 100.1]
    breakout_closes = [100.4, 100.9, 101.5]
    closes = range_closes + breakout_closes
    highs = [100.5] * 6 + [c + 0.2 for c in breakout_closes]
    lows = [99.5] * 6 + [c - 0.2 for c in breakout_closes]
    today = make_bars(
        closes,
        highs,
        lows,
        timeframe="5m",
        start=datetime(2026, 1, 6, 14, 0, tzinfo=UTC),
        step=timedelta(minutes=5),
    )
    return prev_day + today


# --- scan helpers ---------------------------------------------------------------


def scan_signals(plugin, bars: list[Bar]) -> list[tuple[int, object]]:
    """Evaluate every prefix; returns [(bar_index, signal), ...]."""
    found = []
    for i in range(2, len(bars) + 1):
        signal = plugin.evaluate(bars[:i])
        if signal is not None:
            found.append((i - 1, signal))
    return found


def first_signal_prefix(plugin, bars: list[Bar]) -> Optional[list[Bar]]:
    """Shortest bar prefix for which the plugin fires (or None)."""
    for i in range(2, len(bars) + 1):
        if plugin.evaluate(bars[:i]) is not None:
            return bars[:i]
    return None
