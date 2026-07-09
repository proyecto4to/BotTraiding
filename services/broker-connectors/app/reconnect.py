"""Shared reconnection helper: exponential backoff with jitter.

Used by every connector's ``connect()`` so a dropped transport (broker
sandbox restart, transient network blip) is retried with backoff instead of
failing the first time or hammering the broker.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ReconnectError(Exception):
    """Raised when all reconnection attempts are exhausted."""


async def reconnect_with_backoff(
    attempt: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 5,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    jitter: float = 0.25,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Call ``attempt()`` repeatedly until it succeeds or attempts run out.

    Delay grows as ``base_delay * 2 ** (n - 1)``, capped at ``max_delay``,
    with up to ``jitter`` fraction of extra random delay added to avoid
    thundering-herd reconnects.
    """
    last_exc: Exception | None = None
    for attempt_number in range(1, max_attempts + 1):
        try:
            return await attempt()
        except Exception as exc:  # noqa: BLE001 - must catch any transport failure to retry
            last_exc = exc
            if attempt_number == max_attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt_number - 1)))
            delay += random.uniform(0, jitter * delay)
            logger.warning(
                "connection attempt %d/%d failed: %s; retrying in %.2fs",
                attempt_number,
                max_attempts,
                exc,
                delay,
            )
            await sleep(delay)
    raise ReconnectError(f"failed to connect after {max_attempts} attempts") from last_exc
