"""Market regime classification (Fase 11).

Statistical baseline, no ML: the ``RegimeDetector`` interface exists so a
trained model can replace ``StatisticalRegimeDetector`` later without
touching any consumer (docs/ARCHITECTURE.md: la IA no sustituye las
reglas de trading - the regime is an INPUT to strategy selection, never
a trade signal).

Measures over a Bar series (oldest first):

- trend: OLS regression of log-close on bar index over the last
  ``trend_window`` bars -> slope (log-return per bar) + R². A trend is
  declared only when the slope clears ``slope_threshold`` AND the fit
  explains enough variance (R² >= ``r2_threshold``).
- range detection: Kaufman efficiency ratio (net move / path length), a
  cheap Hurst-like proxy; low ER reinforces "sideways".
- volatility: rolling std of log returns over ``vol_window`` bars; the
  latest value is ranked (mid-rank percentile) against its own history,
  so "high" means "high for this instrument", not an absolute number.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from trading_contracts import Bar

TrendLabel = Literal["up", "down", "sideways"]
VolatilityLabel = Literal["low", "normal", "high"]


class RegimeState(BaseModel):
    """Classification of the current market regime."""

    trend: TrendLabel
    volatility: VolatilityLabel
    confidence: float = Field(ge=0.0, le=1.0)
    #: diagnostic measures backing the labels (slope, r2, er, percentile...).
    metrics: dict[str, Any] = Field(default_factory=dict)


class RegimeDetector(ABC):
    """Interface: an ML model can replace the statistical baseline later."""

    #: minimum bars the detector needs to produce a classification.
    min_bars: int = 2

    @abstractmethod
    def detect(self, bars: Sequence[Bar]) -> RegimeState:
        """Classify the regime of a Bar series (oldest first)."""


def _closes(bars: Sequence[Bar]) -> np.ndarray:
    return np.asarray([b.close for b in bars], dtype=float)


def _trend_regression(log_closes: np.ndarray) -> tuple[float, float]:
    """OLS fit of log-close vs bar index. Returns (slope, r_squared)."""
    n = len(log_closes)
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, log_closes, 1)
    fitted = slope * x + intercept
    ss_res = float(np.sum((log_closes - fitted) ** 2))
    ss_tot = float(np.sum((log_closes - log_closes.mean()) ** 2))
    r2 = 0.0 if ss_tot <= 0.0 else max(0.0, 1.0 - ss_res / ss_tot)
    return float(slope), r2


def _efficiency_ratio(closes: np.ndarray) -> float:
    """Kaufman ER: |net move| / sum(|bar-to-bar moves|), in [0, 1]."""
    diffs = np.abs(np.diff(closes))
    path = float(diffs.sum())
    if path <= 0.0:
        return 0.0
    return float(abs(closes[-1] - closes[0]) / path)


def _midrank_percentile(history: np.ndarray, current: float) -> float:
    """Fraction of history strictly below current + half the ties.

    Mid-rank keeps a constant-volatility series at ~0.5 ("normal")
    instead of the 1.0 a plain <= count would give.
    """
    if len(history) == 0:
        return 0.5
    below = float(np.count_nonzero(history < current))
    equal = float(np.count_nonzero(history == current))
    return (below + 0.5 * equal) / float(len(history))


class StatisticalRegimeDetector(RegimeDetector):
    """Deterministic, dependency-light baseline classifier."""

    def __init__(
        self,
        trend_window: int = 64,
        vol_window: int = 16,
        slope_threshold: float = 4e-4,
        r2_threshold: float = 0.35,
        er_threshold: float = 0.25,
        vol_low_pct: float = 0.25,
        vol_high_pct: float = 0.75,
    ) -> None:
        if trend_window < 8:
            raise ValueError("trend_window must be >= 8")
        if vol_window < 2:
            raise ValueError("vol_window must be >= 2")
        self.trend_window = trend_window
        self.vol_window = vol_window
        self.slope_threshold = slope_threshold
        self.r2_threshold = r2_threshold
        self.er_threshold = er_threshold
        self.vol_low_pct = vol_low_pct
        self.vol_high_pct = vol_high_pct
        self.min_bars = max(trend_window, 2 * vol_window)

    # --- volatility ---------------------------------------------------------

    def _rolling_vol(self, log_returns: np.ndarray) -> np.ndarray:
        w = self.vol_window
        n = len(log_returns)
        if n < w:
            return np.empty(0)
        out = np.empty(n - w + 1)
        for i in range(w - 1, n):
            out[i - w + 1] = log_returns[i - w + 1 : i + 1].std()
        return out

    # --- classification -------------------------------------------------------

    def detect(self, bars: Sequence[Bar]) -> RegimeState:
        if len(bars) < self.min_bars:
            raise ValueError(
                f"need at least {self.min_bars} bars to classify a regime "
                f"(got {len(bars)})"
            )
        closes = _closes(bars)
        if np.any(closes <= 0.0):
            raise ValueError("bars contain non-positive close prices")

        log_closes = np.log(closes)
        window = log_closes[-self.trend_window :]
        slope, r2 = _trend_regression(window)
        er = _efficiency_ratio(closes[-self.trend_window :])

        trending = abs(slope) >= self.slope_threshold and r2 >= self.r2_threshold
        if trending and er >= self.er_threshold:
            trend: TrendLabel = "up" if slope > 0 else "down"
            # confidence grows with fit quality and slope clearance.
            trend_conf = min(1.0, r2) * min(
                1.0, abs(slope) / (2.0 * self.slope_threshold)
            )
        else:
            trend = "sideways"
            trend_conf = min(1.0, 1.0 - r2 + (1.0 - er) * 0.25)

        log_returns = np.diff(log_closes)
        vols = self._rolling_vol(log_returns)
        current_vol = float(vols[-1]) if len(vols) else 0.0
        pct = _midrank_percentile(vols[:-1], current_vol) if len(vols) > 1 else 0.5
        if pct <= self.vol_low_pct:
            volatility: VolatilityLabel = "low"
            vol_conf = (self.vol_low_pct - pct) / self.vol_low_pct
        elif pct >= self.vol_high_pct:
            volatility = "high"
            vol_conf = (pct - self.vol_high_pct) / (1.0 - self.vol_high_pct)
        else:
            volatility = "normal"
            mid = (self.vol_low_pct + self.vol_high_pct) / 2.0
            half = (self.vol_high_pct - self.vol_low_pct) / 2.0
            vol_conf = 1.0 - abs(pct - mid) / half

        confidence = 0.6 * _clamp(trend_conf) + 0.4 * _clamp(vol_conf)
        return RegimeState(
            trend=trend,
            volatility=volatility,
            confidence=round(_clamp(confidence), 4),
            metrics={
                "slope": slope,
                "r_squared": r2,
                "efficiency_ratio": er,
                "volatility": current_vol,
                "volatility_percentile": pct,
                "bars_used": len(bars),
                "trend_window": self.trend_window,
                "vol_window": self.vol_window,
                "detector": "statistical",
            },
        )


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if math.isnan(value):
        return lo
    return max(lo, min(hi, value))


#: default detector used by the API; swappable for an ML implementation.
default_detector: RegimeDetector = StatisticalRegimeDetector()
