"""Anomaly detection on performance/market series (Fase 11).

Two cheap, robust checks - flags are ADVISORY, they never act:

- rolling z-score: each point is compared against the mean/std of the
  PREVIOUS ``window`` points (the point itself is excluded so a spike
  cannot dampen its own baseline). |z| >= threshold -> flag.
- drawdown velocity: on an equity curve, how much the drawdown deepened
  within the last ``window`` observations. A slow 10% bleed over months
  and a 10% air-pocket in an hour are different animals; this catches
  the second.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

AnomalyType = Literal["return_zscore", "drawdown_velocity"]
Severity = Literal["medium", "high", "critical"]


class AnomalyFlag(BaseModel):
    strategy_key: str
    anomaly_type: AnomalyType
    severity: Severity
    #: index into the submitted series where the anomaly fired.
    index: int
    value: float
    threshold: float
    detail: str = ""


class SeriesInput(BaseModel):
    """One series to scan. kind:

    - "returns": per-period returns/PnL -> rolling z-score check;
    - "equity": equity curve -> drawdown-velocity check.
    """

    strategy_key: str
    kind: Literal["returns", "equity"] = "returns"
    values: list[float] = Field(min_length=1)


def _zscore_severity(z: float, threshold: float) -> Severity:
    if z >= threshold + 3.0:
        return "critical"
    if z >= threshold + 1.5:
        return "high"
    return "medium"


def detect_zscore_anomalies(
    strategy_key: str,
    values: Sequence[float],
    window: int = 20,
    threshold: float = 3.0,
) -> list[AnomalyFlag]:
    """Flag points whose |z| vs the trailing window exceeds *threshold*."""
    v = np.asarray(values, dtype=float)
    flags: list[AnomalyFlag] = []
    for i in range(window, len(v)):
        past = v[i - window : i]
        mean = float(past.mean())
        std = float(past.std())
        if std <= 0.0:
            # flat baseline: any deviation at all is off-script.
            if v[i] != mean:
                flags.append(
                    AnomalyFlag(
                        strategy_key=strategy_key,
                        anomaly_type="return_zscore",
                        severity="critical",
                        index=i,
                        value=float(v[i]),
                        threshold=threshold,
                        detail="deviation from a perfectly flat baseline",
                    )
                )
            continue
        z = abs(v[i] - mean) / std
        if z >= threshold:
            flags.append(
                AnomalyFlag(
                    strategy_key=strategy_key,
                    anomaly_type="return_zscore",
                    severity=_zscore_severity(z, threshold),
                    index=i,
                    value=float(v[i]),
                    threshold=threshold,
                    detail=f"|z|={z:.2f} vs trailing {window}-point window",
                )
            )
    return flags


def _velocity_severity(velocity: float, threshold: float) -> Severity:
    if velocity >= 2.0 * threshold:
        return "critical"
    if velocity >= 1.5 * threshold:
        return "high"
    return "medium"


def detect_drawdown_velocity(
    strategy_key: str,
    equity: Sequence[float],
    window: int = 10,
    threshold: float = 0.10,
) -> list[AnomalyFlag]:
    """Flag points where drawdown deepened >= *threshold* within *window*."""
    eq = np.asarray(equity, dtype=float)
    if len(eq) == 0 or np.any(eq <= 0.0):
        raise ValueError("equity curve must be non-empty and positive")
    peaks = np.maximum.accumulate(eq)
    dd = 1.0 - eq / peaks  # 0 = at peak, 0.2 = 20% under water
    flags: list[AnomalyFlag] = []
    for i in range(window, len(eq)):
        velocity = float(dd[i] - dd[i - window])
        if velocity >= threshold:
            flags.append(
                AnomalyFlag(
                    strategy_key=strategy_key,
                    anomaly_type="drawdown_velocity",
                    severity=_velocity_severity(velocity, threshold),
                    index=i,
                    value=velocity,
                    threshold=threshold,
                    detail=(
                        f"drawdown deepened {velocity:.1%} within "
                        f"{window} observations (now {dd[i]:.1%})"
                    ),
                )
            )
    return flags


def detect_anomalies(
    series: SeriesInput,
    zscore_window: int = 20,
    zscore_threshold: float = 3.0,
    dd_window: int = 10,
    dd_threshold: float = 0.10,
) -> list[AnomalyFlag]:
    """Dispatch a SeriesInput to the check matching its kind."""
    if series.kind == "returns":
        return detect_zscore_anomalies(
            series.strategy_key, series.values, zscore_window, zscore_threshold
        )
    return detect_drawdown_velocity(
        series.strategy_key, series.values, dd_window, dd_threshold
    )
