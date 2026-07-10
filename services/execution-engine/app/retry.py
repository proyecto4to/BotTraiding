"""Retry with exponential backoff for transient transport errors.

Same pattern as broker-connectors' reconnect helper (implemented locally:
services never import each other's code). Only TransientTransportError is
retried; PermanentTransportError (4xx-style failures) propagates
immediately.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger("execution-engine.retry")

T = TypeVar("T")


class TransientTransportError(Exception):
    """Recoverable transport failure (network blip, 5xx, broker reconnecting)."""


class PermanentTransportError(Exception):
    """Non-recoverable transport failure; retrying would not help."""


class RetryExhaustedError(Exception):
    """All retry attempts failed with transient errors."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        super().__init__(f"transport failed after {attempts} attempts: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


async def retry_with_backoff(
    attempt: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 5.0,
    jitter: float = 0.25,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[T, int]:
    """Call ``attempt()`` until success or attempts run out.

    Returns ``(result, attempts_used)``. Delay grows as
    ``base_delay * 2 ** (n - 1)``, capped at ``max_delay``, plus up to
    ``jitter`` fraction of random extra delay.
    """
    last_exc: Exception | None = None
    for attempt_number in range(1, max_attempts + 1):
        try:
            return await attempt(), attempt_number
        except TransientTransportError as exc:
            last_exc = exc
            if attempt_number == max_attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt_number - 1)))
            delay += random.uniform(0, jitter * delay)
            logger.warning(
                "transport attempt %d/%d failed: %s; retrying in %.2fs",
                attempt_number,
                max_attempts,
                exc,
                delay,
            )
            await sleep(delay)
    raise RetryExhaustedError(max_attempts, last_exc or Exception("unknown"))
