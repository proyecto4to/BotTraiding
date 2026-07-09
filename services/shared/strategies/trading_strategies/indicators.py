"""Technical indicators in plain Python/numpy (no TA-Lib dependency).

Every function takes plain sequences of floats and returns a numpy array
aligned with the input, padded with ``nan`` during the warm-up window.
Strategies must guard against ``nan`` before using a value (see
``is_nan``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


def is_nan(value: float) -> bool:
    """True when *value* is NaN (works for numpy scalars and floats)."""
    return math.isnan(float(value))


def _arr(values: Sequence[float]) -> np.ndarray:
    return np.asarray(values, dtype=float)


def sma(values: Sequence[float], period: int) -> np.ndarray:
    """Simple moving average."""
    v = _arr(values)
    n = len(v)
    out = np.full(n, np.nan)
    if period <= 0 or n < period:
        return out
    cumsum = np.cumsum(np.insert(v, 0, 0.0))
    out[period - 1:] = (cumsum[period:] - cumsum[:-period]) / period
    return out


def ema(values: Sequence[float], period: int) -> np.ndarray:
    """Exponential moving average seeded with the SMA of the first window."""
    v = _arr(values)
    n = len(v)
    out = np.full(n, np.nan)
    if period <= 0 or n < period:
        return out
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = v[:period].mean()
    for i in range(period, n):
        out[i] = alpha * v[i] + (1.0 - alpha) * out[i - 1]
    return out


def _wilder(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder smoothing seeded with the mean of the first window."""
    n = len(values)
    out = np.full(n, np.nan)
    if period <= 0 or n < period:
        return out
    out[period - 1] = values[:period].mean()
    for i in range(period, n):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


def rsi(closes: Sequence[float], period: int = 14) -> np.ndarray:
    """Wilder RSI. Flat data (no gains, no losses) is defined as 50."""
    c = _arr(closes)
    n = len(c)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    delta = np.diff(c)
    gains = np.clip(delta, 0.0, None)
    losses = np.clip(-delta, 0.0, None)
    avg_gain = _wilder(gains, period)
    avg_loss = _wilder(losses, period)
    for i in range(period - 1, n - 1):
        g, l = avg_gain[i], avg_loss[i]
        if math.isnan(g) or math.isnan(l):
            continue
        idx = i + 1
        if g == 0.0 and l == 0.0:
            out[idx] = 50.0
        elif l == 0.0:
            out[idx] = 100.0
        else:
            out[idx] = 100.0 - 100.0 / (1.0 + g / l)
    return out


def true_range(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> np.ndarray:
    h, l, c = _arr(highs), _arr(lows), _arr(closes)
    n = len(c)
    tr = np.full(n, np.nan)
    if n == 0:
        return tr
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    return tr


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> np.ndarray:
    """Average True Range (Wilder smoothing)."""
    return _wilder(true_range(highs, lows, closes), period)


def macd(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (macd_line, signal_line, histogram)."""
    c = _arr(closes)
    n = len(c)
    line = ema(c, fast) - ema(c, slow)
    sig = np.full(n, np.nan)
    valid_start = slow - 1
    if n - valid_start >= signal:
        sig[valid_start:] = ema(line[valid_start:], signal)
    hist = line - sig
    return line, sig, hist


def rolling_std(values: Sequence[float], period: int, ddof: int = 0) -> np.ndarray:
    v = _arr(values)
    n = len(v)
    out = np.full(n, np.nan)
    if period <= 0 or n < period:
        return out
    for i in range(period - 1, n):
        out[i] = v[i - period + 1 : i + 1].std(ddof=ddof)
    return out


def bollinger(
    closes: Sequence[float], period: int = 20, num_std: float = 2.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (middle, upper, lower) Bollinger bands."""
    mid = sma(closes, period)
    sd = rolling_std(closes, period)
    return mid, mid + num_std * sd, mid - num_std * sd


def donchian(
    highs: Sequence[float], lows: Sequence[float], period: int = 20
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (upper, lower): rolling max of highs / min of lows."""
    h, l = _arr(highs), _arr(lows)
    n = len(h)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(period - 1, n):
        upper[i] = h[i - period + 1 : i + 1].max()
        lower[i] = l[i - period + 1 : i + 1].min()
    return upper, lower


def keltner(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 20,
    mult: float = 1.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keltner channel: EMA(close) +/- mult * ATR. Returns (mid, upper, lower)."""
    mid = ema(closes, period)
    a = atr(highs, lows, closes, period)
    return mid, mid + mult * a, mid - mult * a


def roc(closes: Sequence[float], period: int) -> np.ndarray:
    """Rate of change in percent over *period* bars."""
    c = _arr(closes)
    n = len(c)
    out = np.full(n, np.nan)
    for i in range(period, n):
        base = c[i - period]
        if base != 0.0:
            out[i] = (c[i] / base - 1.0) * 100.0
    return out


def zscore(closes: Sequence[float], period: int = 20) -> np.ndarray:
    """Rolling z-score of close vs its SMA; 0 when the window is flat."""
    c = _arr(closes)
    m = sma(c, period)
    sd = rolling_std(c, period)
    n = len(c)
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        if math.isnan(m[i]):
            continue
        out[i] = (c[i] - m[i]) / sd[i] if sd[i] > 0.0 else 0.0
    return out


def session_vwap(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
) -> np.ndarray:
    """Cumulative volume-weighted average price over the given bars.

    The caller is responsible for slicing bars to a single session.
    """
    h, l, c, v = _arr(highs), _arr(lows), _arr(closes), _arr(volumes)
    typical = (h + l + c) / 3.0
    cum_tv = np.cumsum(typical * v)
    cum_v = np.cumsum(v)
    out = np.full(len(c), np.nan)
    nonzero = cum_v > 0.0
    out[nonzero] = cum_tv[nonzero] / cum_v[nonzero]
    return out


def highest(values: Sequence[float], period: int) -> np.ndarray:
    v = _arr(values)
    n = len(v)
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        out[i] = v[i - period + 1 : i + 1].max()
    return out


def lowest(values: Sequence[float], period: int) -> np.ndarray:
    v = _arr(values)
    n = len(v)
    out = np.full(n, np.nan)
    for i in range(period - 1, n):
        out[i] = v[i - period + 1 : i + 1].min()
    return out
