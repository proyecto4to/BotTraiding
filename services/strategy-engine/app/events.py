"""signal.created publishing seam (docs/ARCHITECTURE.md seccion 4/7).

Every TradeSignal produced by /strategies/{id}/evaluate is published to
NATS on subject ``signal.created`` when NATS_URL is configured AND
reachable; otherwise a logging no-op publisher is used so evaluation
never depends on the event bus (tests run on the fallback).
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

from trading_contracts import TradeSignal

logger = logging.getLogger("strategy-engine.events")

SIGNAL_CREATED_SUBJECT = "signal.created"


class SignalPublisher(ABC):
    @abstractmethod
    async def publish_signal(self, signal: TradeSignal) -> None:
        ...


class LoggingSignalPublisher(SignalPublisher):
    """No-op fallback: logs the event instead of publishing it."""

    async def publish_signal(self, signal: TradeSignal) -> None:
        logger.info(
            "signal.created (fallback, not published): %s",
            signal.model_dump_json(),
        )


class NatsSignalPublisher(SignalPublisher):
    """Publishes to NATS; degrades to logging when the bus is unreachable."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._fallback = LoggingSignalPublisher()

    async def publish_signal(self, signal: TradeSignal) -> None:
        try:
            import nats  # imported lazily so the dependency stays optional

            client = await nats.connect(
                self._url,
                connect_timeout=2,
                allow_reconnect=False,
                max_reconnect_attempts=1,
            )
            try:
                await client.publish(
                    SIGNAL_CREATED_SUBJECT,
                    signal.model_dump_json().encode("utf-8"),
                )
                await client.flush(timeout=2)
            finally:
                await client.close()
        except Exception as exc:  # noqa: BLE001 - never break evaluation
            logger.warning("NATS unreachable (%s); using logging fallback", exc)
            await self._fallback.publish_signal(signal)


def build_publisher() -> SignalPublisher:
    url = os.environ.get("NATS_URL")
    if not url:
        logger.info("NATS_URL not set; signal.created uses logging fallback")
        return LoggingSignalPublisher()
    try:
        import nats  # noqa: F401
    except ImportError:
        logger.warning("nats-py not installed; signal.created uses logging fallback")
        return LoggingSignalPublisher()
    return NatsSignalPublisher(url)


_publisher: Optional[SignalPublisher] = None


def get_publisher() -> SignalPublisher:
    global _publisher
    if _publisher is None:
        _publisher = build_publisher()
    return _publisher


def set_publisher(publisher: Optional[SignalPublisher]) -> None:
    """Dependency-injection hook (used by tests)."""
    global _publisher
    _publisher = publisher
