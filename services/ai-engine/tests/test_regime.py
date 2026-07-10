"""Regime classifier on synthetic trending/ranging/volatile series."""

from __future__ import annotations

import pytest

from app.regime import StatisticalRegimeDetector

from tests.synthetic import (
    constant_vol_trend_closes,
    make_bars,
    ranging_closes,
    trending_closes,
    vol_shift_closes,
)

detector = StatisticalRegimeDetector()


def test_uptrend_is_labelled_up() -> None:
    bars = make_bars(trending_closes(drift=0.002))
    state = detector.detect(bars)
    assert state.trend == "up"
    assert state.metrics["slope"] > 0
    assert state.metrics["r_squared"] > 0.8
    assert state.confidence > 0.3


def test_downtrend_is_labelled_down() -> None:
    bars = make_bars(trending_closes(drift=-0.002))
    state = detector.detect(bars)
    assert state.trend == "down"
    assert state.metrics["slope"] < 0


def test_range_is_labelled_sideways() -> None:
    bars = make_bars(ranging_closes())
    state = detector.detect(bars)
    assert state.trend == "sideways"


def test_constant_vol_trend_is_normal_volatility() -> None:
    bars = make_bars(constant_vol_trend_closes())
    state = detector.detect(bars)
    assert state.trend == "up"
    assert state.volatility == "normal"
    assert state.metrics["volatility_percentile"] == 0.5


def test_vol_explosion_is_labelled_high() -> None:
    bars = make_bars(vol_shift_closes())
    state = detector.detect(bars)
    assert state.volatility == "high"
    assert state.metrics["volatility_percentile"] >= 0.75


def test_vol_collapse_is_labelled_low() -> None:
    # wild first, dead calm at the end -> current vol ranks low vs history
    closes = vol_shift_closes(n_quiet=50, n_wild=150)
    closes = closes[::-1]  # reverse: wild first, quiet last
    state = detector.detect(make_bars(closes))
    assert state.volatility == "low"


def test_too_few_bars_raises() -> None:
    bars = make_bars(trending_closes(n=10))
    with pytest.raises(ValueError, match="need at least"):
        detector.detect(bars)


def test_confidence_bounds_and_metrics_present() -> None:
    state = detector.detect(make_bars(trending_closes()))
    assert 0.0 <= state.confidence <= 1.0
    for key in ("slope", "r_squared", "efficiency_ratio", "volatility_percentile"):
        assert key in state.metrics
