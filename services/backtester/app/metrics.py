"""Performance metrics for backtest results (Fase 8).

Pure numpy functions over (a) the mark-to-market equity curve (one point
per bar) and (b) the closed-trade net PnL list. Each function documents its
exact convention so unit tests can assert hand-computed values.

Conventions:
- Per-bar simple returns: r_i = equity_i / equity_{i-1} - 1.
- Sharpe (annualized): mean(r) / std(r, ddof=1) * sqrt(periods_per_year).
  ``periods_per_year`` is configurable per run (e.g. 8760 for 1h crypto
  bars, 252 for daily stock bars). 0.0 when std is 0 or < 2 returns.
- Sortino: mean(r) / downside_dev * sqrt(periods_per_year) where
  downside_dev = sqrt(mean(min(r, 0)^2)) over ALL returns (full-series
  denominator convention). None when there are no negative returns.
- Max drawdown: max(1 - equity / running_peak), as a positive fraction.
- CAGR: (end/start)^(periods_per_year / n_periods) - 1 with
  n_periods = len(equity) - 1. -1.0 if equity ends <= 0.
- Calmar: CAGR / max_drawdown. None when max_drawdown == 0.
- Profit factor: gross_wins / abs(gross_losses). None when no losing
  trades (undefined rather than infinite so it stays JSON-safe).
- Expectancy: mean net PnL per closed trade (account currency).
- Win rate: winning trades (pnl > 0) / total trades. Zero-PnL trades
  count as non-wins.
- Exposure %: fraction of bars with an open position, in [0, 100].
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Optional

import numpy as np

DEFAULT_PERIODS_PER_YEAR = 252.0


def bar_returns(equity: Sequence[float]) -> np.ndarray:
    """Per-bar simple returns of the equity curve (length = len(equity)-1)."""
    eq = np.asarray(equity, dtype=float)
    if eq.size < 2:
        return np.empty(0)
    prev = eq[:-1]
    out = np.zeros(eq.size - 1)
    nonzero = prev != 0.0
    out[nonzero] = eq[1:][nonzero] / prev[nonzero] - 1.0
    return out


def sharpe_ratio(
    returns: Sequence[float],
    periods_per_year: float = DEFAULT_PERIODS_PER_YEAR,
    risk_free_rate: float = 0.0,
) -> float:
    """Annualized Sharpe; ``risk_free_rate`` is per-period. 0.0 if undefined."""
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    excess = r - risk_free_rate
    std = float(excess.std(ddof=1))
    if std == 0.0:
        return 0.0
    return float(excess.mean() / std * math.sqrt(periods_per_year))


def sortino_ratio(
    returns: Sequence[float],
    periods_per_year: float = DEFAULT_PERIODS_PER_YEAR,
    risk_free_rate: float = 0.0,
) -> Optional[float]:
    """Annualized Sortino (full-series downside deviation). None if no
    negative excess returns (undefined)."""
    r = np.asarray(returns, dtype=float)
    if r.size < 2:
        return 0.0
    excess = r - risk_free_rate
    downside = np.minimum(excess, 0.0)
    downside_dev = float(np.sqrt(np.mean(downside**2)))
    if downside_dev == 0.0:
        return None
    return float(excess.mean() / downside_dev * math.sqrt(periods_per_year))


def max_drawdown(equity: Sequence[float]) -> float:
    """Deepest peak-to-trough decline as a positive fraction (0.25 = -25%)."""
    eq = np.asarray(equity, dtype=float)
    if eq.size == 0:
        return 0.0
    peaks = np.maximum.accumulate(eq)
    valid = peaks > 0.0
    if not valid.any():
        return 0.0
    dd = np.zeros_like(eq)
    dd[valid] = 1.0 - eq[valid] / peaks[valid]
    return float(dd.max())


def cagr(
    equity: Sequence[float],
    periods_per_year: float = DEFAULT_PERIODS_PER_YEAR,
) -> float:
    """Compound annual growth rate of the equity curve."""
    eq = np.asarray(equity, dtype=float)
    if eq.size < 2 or eq[0] <= 0.0:
        return 0.0
    if eq[-1] <= 0.0:
        return -1.0
    n_periods = eq.size - 1
    return float((eq[-1] / eq[0]) ** (periods_per_year / n_periods) - 1.0)


def calmar_ratio(cagr_value: float, max_dd: float) -> Optional[float]:
    """CAGR / max drawdown. None when there is no drawdown (undefined)."""
    if max_dd <= 0.0:
        return None
    return float(cagr_value / max_dd)


def profit_factor(trade_pnls: Sequence[float]) -> Optional[float]:
    """Gross wins / gross losses. None if no losses (or no trades)."""
    pnls = np.asarray(trade_pnls, dtype=float)
    if pnls.size == 0:
        return None
    gross_wins = float(pnls[pnls > 0].sum())
    gross_losses = float(-pnls[pnls < 0].sum())
    if gross_losses == 0.0:
        return None
    return gross_wins / gross_losses


def expectancy(trade_pnls: Sequence[float]) -> float:
    """Mean net PnL per closed trade; 0.0 with no trades."""
    pnls = np.asarray(trade_pnls, dtype=float)
    if pnls.size == 0:
        return 0.0
    return float(pnls.mean())


def win_rate(trade_pnls: Sequence[float]) -> float:
    """Fraction of trades with pnl > 0, in [0, 1]. 0.0 with no trades."""
    pnls = np.asarray(trade_pnls, dtype=float)
    if pnls.size == 0:
        return 0.0
    return float((pnls > 0).sum() / pnls.size)


def average_win(trade_pnls: Sequence[float]) -> Optional[float]:
    pnls = np.asarray(trade_pnls, dtype=float)
    wins = pnls[pnls > 0]
    return float(wins.mean()) if wins.size else None


def average_loss(trade_pnls: Sequence[float]) -> Optional[float]:
    """Mean of losing trades (a negative number). None if no losses."""
    pnls = np.asarray(trade_pnls, dtype=float)
    losses = pnls[pnls < 0]
    return float(losses.mean()) if losses.size else None


def exposure_pct(bars_in_position: int, total_bars: int) -> float:
    """Percentage of bars with an open position, in [0, 100]."""
    if total_bars <= 0:
        return 0.0
    return 100.0 * bars_in_position / total_bars


def summarize(
    equity: Sequence[float],
    trade_pnls: Sequence[float],
    periods_per_year: float = DEFAULT_PERIODS_PER_YEAR,
    bars_in_position: int = 0,
    risk_free_rate: float = 0.0,
) -> dict:
    """All metrics in one JSON-safe dict (floats / ints / None)."""
    eq = np.asarray(equity, dtype=float)
    returns = bar_returns(eq)
    total_return = float(eq[-1] / eq[0] - 1.0) if eq.size >= 2 and eq[0] > 0 else 0.0
    growth = cagr(eq, periods_per_year)
    max_dd = max_drawdown(eq)
    return {
        "total_return": total_return,
        "final_equity": float(eq[-1]) if eq.size else 0.0,
        "cagr": growth,
        "sharpe": sharpe_ratio(returns, periods_per_year, risk_free_rate),
        "sortino": sortino_ratio(returns, periods_per_year, risk_free_rate),
        "calmar": calmar_ratio(growth, max_dd),
        "max_drawdown": max_dd,
        "profit_factor": profit_factor(trade_pnls),
        "expectancy": expectancy(trade_pnls),
        "win_rate": win_rate(trade_pnls),
        "trade_count": int(len(trade_pnls)),
        "avg_win": average_win(trade_pnls),
        "avg_loss": average_loss(trade_pnls),
        "exposure_pct": exposure_pct(bars_in_position, max(eq.size, 1)),
        "periods_per_year": float(periods_per_year),
    }
