"""Anomaly detection: z-score flags and drawdown-velocity flags."""

from __future__ import annotations

import pytest

from app.anomaly import (
    SeriesInput,
    detect_anomalies,
    detect_drawdown_velocity,
    detect_zscore_anomalies,
)


def test_zscore_flags_outlier() -> None:
    # 30 small returns, then a -25% shock: |z| >> 3
    values = [0.001, -0.001] * 15 + [-0.25]
    flags = detect_zscore_anomalies("s1", values, window=20, threshold=3.0)
    assert len(flags) == 1
    flag = flags[0]
    assert flag.anomaly_type == "return_zscore"
    assert flag.index == 30
    assert flag.value == pytest.approx(-0.25)
    assert flag.severity == "critical"
    assert flag.strategy_key == "s1"


def test_zscore_quiet_series_has_no_flags() -> None:
    values = [0.001, -0.0012, 0.0008, -0.0009] * 20
    assert detect_zscore_anomalies("s1", values, window=20) == []


def test_zscore_flat_baseline_deviation_is_critical() -> None:
    values = [0.0] * 25 + [0.05]
    flags = detect_zscore_anomalies("s1", values, window=20)
    assert len(flags) == 1
    assert flags[0].severity == "critical"


def test_drawdown_velocity_flags_fast_crash() -> None:
    # equity grinds up, then loses ~30% in 5 observations
    equity = [100.0 + i for i in range(30)]
    crash = [equity[-1] * (1.0 - 0.06 * k) for k in range(1, 6)]
    flags = detect_drawdown_velocity("s2", equity + crash, window=10, threshold=0.10)
    assert flags, "fast crash must be flagged"
    assert all(f.anomaly_type == "drawdown_velocity" for f in flags)
    assert flags[-1].value >= 0.10


def test_drawdown_velocity_slow_bleed_not_flagged() -> None:
    # same total drawdown but spread over 100 observations: velocity low
    equity = [100.0 * (1.0 - 0.002 * i) for i in range(100)]
    flags = detect_drawdown_velocity("s2", equity, window=10, threshold=0.10)
    assert flags == []


def test_drawdown_velocity_rejects_bad_equity() -> None:
    with pytest.raises(ValueError):
        detect_drawdown_velocity("s2", [100.0, -5.0], window=1)


def test_dispatch_by_kind() -> None:
    returns_series = SeriesInput(
        strategy_key="s1", kind="returns", values=[0.001] * 25 + [0.5]
    )
    assert detect_anomalies(returns_series)[0].anomaly_type == "return_zscore"

    equity = [100.0] * 15 + [60.0]
    equity_series = SeriesInput(strategy_key="s1", kind="equity", values=equity)
    assert detect_anomalies(equity_series)[0].anomaly_type == "drawdown_velocity"
