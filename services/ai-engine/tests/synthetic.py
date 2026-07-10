"""Deterministic synthetic Bar series for regime/anomaly tests."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

from trading_contracts import Bar

_T0 = datetime(2026, 1, 1)


def make_bars(closes: list[float], symbol: str = "TEST/USD", timeframe: str = "1h") -> list[Bar]:
    bars = []
    for i, close in enumerate(closes):
        prev = closes[i - 1] if i > 0 else close
        high = max(prev, close) * 1.001
        low = min(prev, close) * 0.999
        bars.append(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                open=prev,
                high=high,
                low=low,
                close=close,
                volume=1_000.0,
                timestamp=_T0 + timedelta(hours=i),
            )
        )
    return bars


def trending_closes(
    n: int = 200,
    start: float = 100.0,
    drift: float = 0.002,
    noise: float = 0.0005,
    seed: int = 7,
) -> list[float]:
    """Geometric drift per bar + small gaussian noise (log space)."""
    rng = random.Random(seed)
    closes = []
    log_price = math.log(start)
    for _ in range(n):
        log_price += drift + rng.gauss(0.0, noise)
        closes.append(math.exp(log_price))
    return closes


def constant_vol_trend_closes(
    n: int = 200,
    start: float = 100.0,
    drift: float = 0.002,
    amplitude: float = 0.001,
) -> list[float]:
    """Uptrend with EXACTLY constant volatility: log-returns alternate
    drift+amplitude / drift-amplitude, so every rolling std window (of
    even length) is identical and the vol percentile is exactly 0.5."""
    closes = []
    log_price = math.log(start)
    for i in range(n):
        log_price += drift + (amplitude if i % 2 == 0 else -amplitude)
        closes.append(math.exp(log_price))
    return closes


def ranging_closes(
    n: int = 200,
    center: float = 100.0,
    amplitude: float = 0.01,
    period: int = 20,
    noise: float = 0.001,
    seed: int = 11,
) -> list[float]:
    """Mean-reverting oscillation around a flat center (no net drift)."""
    rng = random.Random(seed)
    closes = []
    for i in range(n):
        wave = amplitude * math.sin(2.0 * math.pi * i / period)
        closes.append(center * math.exp(wave + rng.gauss(0.0, noise)))
    return closes


def vol_shift_closes(
    n_quiet: int = 150,
    n_wild: int = 50,
    start: float = 100.0,
    quiet_noise: float = 0.0005,
    wild_noise: float = 0.03,
    seed: int = 13,
) -> list[float]:
    """Quiet series whose volatility explodes at the end (no drift)."""
    rng = random.Random(seed)
    closes = []
    log_price = math.log(start)
    for _ in range(n_quiet):
        log_price += rng.gauss(0.0, quiet_noise)
        closes.append(math.exp(log_price))
    for _ in range(n_wild):
        log_price += rng.gauss(0.0, wild_noise)
        closes.append(math.exp(log_price))
    return closes
