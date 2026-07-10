"""Historical data loading for the backtester (Fase 8).

Three ways to obtain a chronological list of shared ``Bar`` contracts:

1. CSV OHLCV files (``parse_csv_bars`` / ``load_csv_file`` /
   ``CsvDataSource``) - path on disk or raw text uploaded in the request.
2. Synthetic data (``generate_synthetic_bars`` / ``SyntheticDataSource``)
   with three regimes - ``trend``, ``range`` (mean-reverting) and
   ``random_walk`` - used by tests and quick strategy sanity checks.
3. ``BrokerHistoricalDataSource`` - the seam through which
   broker-connectors' ``get_historical_data(symbol, timeframe, start, end)``
   will plug in later. Stub today (raises ``NotImplementedError``); it is
   injectable anywhere a ``HistoricalDataSource`` is accepted.

All loaders return bars sorted by timestamp ascending (oldest first), the
order the engine and the strategy plugins require.
"""

from __future__ import annotations

import csv
import io
import math
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import numpy as np

from trading_contracts import Bar

SyntheticRegime = Literal["trend", "range", "random_walk"]

#: Column aliases accepted by the CSV loader (case-insensitive).
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "time", "date", "datetime"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "volume": ("volume", "vol", "v"),
}


class DataLoadError(ValueError):
    """Raised when historical data cannot be loaded/parsed."""


def _parse_timestamp(raw: str) -> datetime:
    """ISO-8601 (with or without tz) or unix epoch seconds/milliseconds."""
    raw = raw.strip()
    try:
        value = float(raw)
    except ValueError:
        pass
    else:
        if value > 1e12:  # epoch milliseconds
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataLoadError(f"unparseable timestamp {raw!r}") from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    lowered = {name.strip().lower(): name for name in fieldnames if name}
    resolved: dict[str, str] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                resolved[canonical] = lowered[alias]
                break
        else:
            if canonical == "volume":
                continue  # volume is optional (defaults to 0)
            raise DataLoadError(f"CSV is missing required column '{canonical}'")
    return resolved


def parse_csv_bars(text: str, symbol: str, timeframe: str) -> list[Bar]:
    """Parse OHLCV CSV text into Bars sorted by timestamp ascending.

    Requires header row with timestamp/open/high/low/close (volume
    optional). Extra columns are ignored.
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise DataLoadError("CSV has no header row")
    columns = _resolve_columns(list(reader.fieldnames))
    bars: list[Bar] = []
    for line_no, row in enumerate(reader, start=2):
        try:
            ts = _parse_timestamp(row[columns["timestamp"]])
            o = float(row[columns["open"]])
            h = float(row[columns["high"]])
            lo = float(row[columns["low"]])
            c = float(row[columns["close"]])
            vol_col = columns.get("volume")
            v = float(row[vol_col]) if vol_col and row.get(vol_col) not in (None, "") else 0.0
        except DataLoadError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise DataLoadError(f"CSV line {line_no}: bad OHLCV row ({exc})") from exc
        if any(math.isnan(x) or math.isinf(x) for x in (o, h, lo, c, v)):
            raise DataLoadError(f"CSV line {line_no}: NaN/inf value")
        bars.append(
            Bar(symbol=symbol, timeframe=timeframe, open=o, high=h, low=lo,
                close=c, volume=v, timestamp=ts)
        )
    if not bars:
        raise DataLoadError("CSV contained no data rows")
    bars.sort(key=lambda b: b.timestamp)
    return bars


def load_csv_file(path: str, symbol: str, timeframe: str) -> list[Bar]:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError as exc:
        raise DataLoadError(f"cannot read CSV file {path!r}: {exc}") from exc
    return parse_csv_bars(text, symbol=symbol, timeframe=timeframe)


def filter_bars(
    bars: list[Bar],
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> list[Bar]:
    """Inclusive [start, end] timestamp filter; naive bounds treated as UTC."""

    def _aware(ts: Optional[datetime]) -> Optional[datetime]:
        if ts is not None and ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    lo, hi = _aware(start), _aware(end)
    return [
        b for b in bars
        if (lo is None or b.timestamp >= lo) and (hi is None or b.timestamp <= hi)
    ]


# --- synthetic data ----------------------------------------------------------

_TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "4h": 240, "1d": 1440,
}


def generate_synthetic_bars(
    regime: SyntheticRegime = "random_walk",
    n_bars: int = 500,
    seed: int = 42,
    start_price: float = 100.0,
    symbol: str = "SYN",
    timeframe: str = "1h",
    start: Optional[datetime] = None,
    drift: float = 0.002,
    volatility: float = 0.01,
    mean_reversion: float = 0.1,
    base_volume: float = 10_000.0,
) -> list[Bar]:
    """Deterministic (seeded) synthetic OHLCV series.

    Regimes:
    - ``trend``: geometric walk with per-bar ``drift`` on log price.
    - ``range``: mean-reverting around ``start_price`` (Ornstein-Uhlenbeck
      style, strength ``mean_reversion``); drift is ignored.
    - ``random_walk``: zero-drift geometric walk.

    Bars are gapless (each open equals the previous close) so gap behaviour
    stays an explicit test fixture rather than a random surprise.
    """
    if n_bars < 2:
        raise DataLoadError("n_bars must be >= 2")
    if regime not in ("trend", "range", "random_walk"):
        raise DataLoadError(f"unknown synthetic regime {regime!r}")
    minutes = _TIMEFRAME_MINUTES.get(timeframe, 60)
    t0 = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    rng = np.random.default_rng(seed)

    closes = np.empty(n_bars)
    price = float(start_price)
    for i in range(n_bars):
        noise = rng.normal(0.0, volatility)
        if regime == "trend":
            price *= math.exp(drift + noise)
        elif regime == "range":
            pull = mean_reversion * (math.log(start_price) - math.log(price))
            price *= math.exp(pull + noise)
        else:  # random_walk
            price *= math.exp(noise)
        closes[i] = max(price, 1e-9)

    highs_extra = np.abs(rng.normal(0.0, volatility / 2.0, n_bars))
    lows_extra = np.abs(rng.normal(0.0, volatility / 2.0, n_bars))
    volumes = base_volume * (1.0 + np.abs(rng.normal(0.0, 0.3, n_bars)))

    bars: list[Bar] = []
    prev_close = float(start_price)
    for i in range(n_bars):
        o, c = prev_close, float(closes[i])
        h = max(o, c) * (1.0 + float(highs_extra[i]))
        lo = min(o, c) * (1.0 - float(lows_extra[i]))
        bars.append(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=float(volumes[i]),
                timestamp=t0 + timedelta(minutes=minutes * i),
            )
        )
        prev_close = c
    return bars


# --- data-source seam ---------------------------------------------------------


class HistoricalDataSource(ABC):
    """Seam for pluggable historical data providers.

    The engine/API only depend on this interface, so swapping CSV/synthetic
    data for real broker history (Fase 3 ``BrokerConnector
    .get_historical_data``) is a constructor change, not an engine change.
    """

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[Bar]:
        """Return bars sorted oldest-first, filtered to [start, end]."""


class CsvDataSource(HistoricalDataSource):
    """Serves bars from a CSV file path or from already-uploaded CSV text."""

    def __init__(self, path: Optional[str] = None, content: Optional[str] = None) -> None:
        if (path is None) == (content is None):
            raise DataLoadError("CsvDataSource needs exactly one of path/content")
        self._path = path
        self._content = content

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[Bar]:
        if self._path is not None:
            bars = load_csv_file(self._path, symbol=symbol, timeframe=timeframe)
        else:
            bars = parse_csv_bars(self._content or "", symbol=symbol, timeframe=timeframe)
        return filter_bars(bars, start, end)


class SyntheticDataSource(HistoricalDataSource):
    """Serves deterministic synthetic bars (see ``generate_synthetic_bars``)."""

    def __init__(
        self,
        regime: SyntheticRegime = "random_walk",
        n_bars: int = 500,
        seed: int = 42,
        start_price: float = 100.0,
        drift: float = 0.002,
        volatility: float = 0.01,
        mean_reversion: float = 0.1,
        base_volume: float = 10_000.0,
        start: Optional[datetime] = None,
    ) -> None:
        self._kwargs = dict(
            regime=regime, n_bars=n_bars, seed=seed, start_price=start_price,
            drift=drift, volatility=volatility, mean_reversion=mean_reversion,
            base_volume=base_volume, start=start,
        )

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[Bar]:
        bars = generate_synthetic_bars(
            symbol=symbol, timeframe=timeframe, **self._kwargs
        )
        return filter_bars(bars, start, end)


class BrokerHistoricalDataSource(HistoricalDataSource):
    """Stub seam for broker-connectors historical data (not wired yet).

    TODO(Fase posterior): call broker-connectors'
    ``get_historical_data(symbol, timeframe, start, end)`` (REST) and map the
    response to shared ``Bar`` contracts. Kept injectable so the API/engine
    need no changes when it lands.
    """

    def __init__(self, base_url: str, broker: str) -> None:
        self.base_url = base_url
        self.broker = broker

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[Bar]:
        raise NotImplementedError(
            "broker-connectors historical data is not wired into the "
            "backtester yet; use CsvDataSource or SyntheticDataSource"
        )
