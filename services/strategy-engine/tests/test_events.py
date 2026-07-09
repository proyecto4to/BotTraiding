"""signal.created publisher seam: NATS when configured, fallback otherwise."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from trading_contracts import OrderSide, TradeSignal

from app import events


def _signal() -> TradeSignal:
    return TradeSignal(
        id=uuid4(),
        strategy_id="sma_crossover",
        symbol="TEST",
        market="crypto",
        side=OrderSide.BUY,
        confidence=0.6,
        timeframe="1h",
        suggested_size=1.0,
        generated_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )


def test_no_nats_url_builds_logging_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NATS_URL", raising=False)
    publisher = events.build_publisher()
    assert isinstance(publisher, events.LoggingSignalPublisher)


def test_logging_publisher_logs_signal(caplog: pytest.LogCaptureFixture) -> None:
    publisher = events.LoggingSignalPublisher()
    with caplog.at_level("INFO", logger="strategy-engine.events"):
        asyncio.run(publisher.publish_signal(_signal()))
    assert any("signal.created" in record.message for record in caplog.records)


def test_unreachable_nats_falls_back_without_raising(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("NATS_URL", "nats://127.0.0.1:9")  # nothing listens here
    publisher = events.build_publisher()
    with caplog.at_level("INFO", logger="strategy-engine.events"):
        asyncio.run(publisher.publish_signal(_signal()))  # must not raise
    assert any("signal.created" in record.message for record in caplog.records)


def test_get_publisher_is_cached_and_resettable() -> None:
    events.set_publisher(None)
    first = events.get_publisher()
    assert events.get_publisher() is first
    replacement = events.LoggingSignalPublisher()
    events.set_publisher(replacement)
    assert events.get_publisher() is replacement
