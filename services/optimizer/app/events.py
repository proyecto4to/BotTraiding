"""Optimizer event publishing seam (docs/ARCHITECTURE.md seccion 7).

``optimizer.promotion.recommended`` is published whenever the walk-forward
gate passes (and ``optimizer.params.applied`` when params were actually
pushed to strategy-engine). NATS when NATS_URL is configured AND
reachable; otherwise a logging no-op publisher (tests run on the
fallback). Same pattern as strategy-engine's signal.created seam.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

logger = logging.getLogger("optimizer.events")

PROMOTION_RECOMMENDED_SUBJECT = "optimizer.promotion.recommended"
PARAMS_APPLIED_SUBJECT = "optimizer.params.applied"


class EventPublisher(ABC):
    @abstractmethod
    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        ...


class LoggingEventPublisher(EventPublisher):
    """No-op fallback: logs the event instead of publishing it."""

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        logger.info(
            "%s (fallback, not published): %s", subject, json.dumps(payload, default=str)
        )


class NatsEventPublisher(EventPublisher):
    """Publishes to NATS; degrades to logging when the bus is unreachable."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._fallback = LoggingEventPublisher()

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
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
                    subject, json.dumps(payload, default=str).encode("utf-8")
                )
                await client.flush(timeout=2)
            finally:
                await client.close()
        except Exception as exc:  # noqa: BLE001 - never break the pipeline
            logger.warning("NATS unreachable (%s); using logging fallback", exc)
            await self._fallback.publish(subject, payload)


def build_publisher() -> EventPublisher:
    url = os.environ.get("NATS_URL")
    if not url:
        logger.info("NATS_URL not set; optimizer events use logging fallback")
        return LoggingEventPublisher()
    try:
        import nats  # noqa: F401
    except ImportError:
        logger.warning("nats-py not installed; optimizer events use logging fallback")
        return LoggingEventPublisher()
    return NatsEventPublisher(url)


_publisher: Optional[EventPublisher] = None


def get_publisher() -> EventPublisher:
    global _publisher
    if _publisher is None:
        _publisher = build_publisher()
    return _publisher


def set_publisher(publisher: Optional[EventPublisher]) -> None:
    """Dependency-injection hook (used by tests)."""
    global _publisher
    _publisher = publisher
