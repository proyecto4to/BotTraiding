"""Tests for app/data.py: CSV parsing, synthetic regimes, source seam."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.data import (
    BrokerHistoricalDataSource,
    CsvDataSource,
    DataLoadError,
    SyntheticDataSource,
    filter_bars,
    generate_synthetic_bars,
    parse_csv_bars,
)

CSV = """timestamp,open,high,low,close,volume
2024-01-01T01:00:00Z,101,102,100,101.5,900
2024-01-01T00:00:00Z,100,101,99,100.5,1000
2024-01-01T02:00:00Z,101.5,103,101,102,1100
"""


def test_parse_csv_sorts_and_maps_columns() -> None:
    bars = parse_csv_bars(CSV, symbol="BTCUSD", timeframe="1h")
    assert [b.open for b in bars] == [100.0, 101.0, 101.5]
    assert bars[0].timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert bars[0].symbol == "BTCUSD" and bars[0].timeframe == "1h"
    assert bars[1].volume == 900.0


def test_parse_csv_epoch_and_aliases_and_optional_volume() -> None:
    text = "time,o,h,l,c\n1704067200,100,101,99,100.5\n"
    bars = parse_csv_bars(text, symbol="X", timeframe="1h")
    assert bars[0].timestamp == datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert bars[0].volume == 0.0  # volume column is optional


def test_parse_csv_missing_column_raises() -> None:
    with pytest.raises(DataLoadError, match="close"):
        parse_csv_bars("timestamp,open,high,low\n2024-01-01,1,2,0\n", "X", "1h")
    with pytest.raises(DataLoadError, match="no data rows"):
        parse_csv_bars("timestamp,open,high,low,close\n", "X", "1h")
    with pytest.raises(DataLoadError):
        parse_csv_bars("timestamp,open,high,low,close\nnot-a-date,1,2,0,1\n", "X", "1h")


def test_filter_bars_inclusive_range() -> None:
    bars = parse_csv_bars(CSV, symbol="X", timeframe="1h")
    out = filter_bars(
        bars,
        start=datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 1, 2, tzinfo=timezone.utc),
    )
    assert len(out) == 2
    # naive bounds are treated as UTC
    out2 = filter_bars(bars, start=datetime(2024, 1, 1, 2))
    assert len(out2) == 1


def test_synthetic_trend_goes_up_and_is_deterministic() -> None:
    a = generate_synthetic_bars("trend", n_bars=300, seed=7, drift=0.003, volatility=0.005)
    b = generate_synthetic_bars("trend", n_bars=300, seed=7, drift=0.003, volatility=0.005)
    assert len(a) == 300
    assert [x.close for x in a] == [x.close for x in b]  # seeded => deterministic
    assert a[-1].close > a[0].close * 1.5  # strong drift dominates
    c = generate_synthetic_bars("trend", n_bars=300, seed=8, drift=0.003, volatility=0.005)
    assert [x.close for x in c] != [x.close for x in a]


def test_synthetic_range_stays_near_anchor() -> None:
    bars = generate_synthetic_bars(
        "range", n_bars=800, seed=11, start_price=100.0,
        volatility=0.01, mean_reversion=0.15,
    )
    closes = [b.close for b in bars]
    assert max(closes) < 150.0 and min(closes) > 66.0


def test_synthetic_bars_are_valid_ohlc_and_gapless() -> None:
    bars = generate_synthetic_bars("random_walk", n_bars=100, seed=3)
    for prev, cur in zip(bars, bars[1:]):
        assert cur.open == pytest.approx(prev.close)  # gapless by construction
        assert cur.timestamp > prev.timestamp
    for b in bars:
        assert b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high
        assert b.volume > 0


def test_synthetic_rejects_bad_input() -> None:
    with pytest.raises(DataLoadError):
        generate_synthetic_bars("trend", n_bars=1)
    with pytest.raises(DataLoadError):
        generate_synthetic_bars("sideways")  # type: ignore[arg-type]


def test_csv_data_source_content_and_validation(tmp_path) -> None:
    src = CsvDataSource(content=CSV)
    bars = src.get_bars("X", "1h")
    assert len(bars) == 3
    path = tmp_path / "bars.csv"
    path.write_text(CSV, encoding="utf-8")
    assert len(CsvDataSource(path=str(path)).get_bars("X", "1h")) == 3
    with pytest.raises(DataLoadError):
        CsvDataSource()
    with pytest.raises(DataLoadError):
        CsvDataSource(path="a.csv", content=CSV)
    with pytest.raises(DataLoadError):
        CsvDataSource(path=str(tmp_path / "missing.csv")).get_bars("X", "1h")


def test_synthetic_data_source_seam() -> None:
    src = SyntheticDataSource(regime="trend", n_bars=50, seed=1)
    bars = src.get_bars("ETHUSD", "4h")
    assert len(bars) == 50
    assert bars[0].symbol == "ETHUSD" and bars[0].timeframe == "4h"


def test_broker_source_is_a_stub_for_now() -> None:
    src = BrokerHistoricalDataSource(base_url="http://broker-connectors:8000", broker="sim")
    with pytest.raises(NotImplementedError):
        src.get_bars("BTCUSD", "1h")
