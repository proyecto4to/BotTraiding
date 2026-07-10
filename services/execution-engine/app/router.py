"""ExecutionRouter: one pipeline, mode-selected transports + order splitting.

The router owns the transport map (paper -> paper-trading, live ->
broker-connectors) and the retry policy. Mode is data: the pipeline asks the
router for the order's execution_mode and everything downstream is
identical (architecture section 10).
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Mapping

from trading_contracts import ExecutionMode, ExecutionReport, Order

from . import config
from .retry import retry_with_backoff
from .transports import ExecutionTransport, LiveTransport, PaperTransport


class ModeUnavailableError(Exception):
    """No transport is registered for the requested execution mode."""


def split_order(quantity: float, max_child_size: float) -> list[float]:
    """Split ``quantity`` into sequential child quantities of at most
    ``max_child_size`` each (0 or negative = no splitting)."""
    if max_child_size <= 0 or quantity <= max_child_size:
        return [quantity]
    children: list[float] = []
    remaining = quantity
    while remaining > 1e-9:
        chunk = min(max_child_size, remaining)
        children.append(round(chunk, 8))
        remaining = round(remaining - chunk, 8)
    return children


class ExecutionRouter:
    def __init__(
        self,
        transports: Mapping[ExecutionMode, ExecutionTransport],
        *,
        max_attempts: int | None = None,
        base_delay: float | None = None,
        max_delay: float | None = None,
        jitter: float | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._transports = dict(transports)
        self._max_attempts = max_attempts if max_attempts is not None else config.retry_max_attempts()
        self._base_delay = base_delay if base_delay is not None else config.retry_base_delay()
        self._max_delay = max_delay if max_delay is not None else config.retry_max_delay()
        self._jitter = jitter if jitter is not None else config.retry_jitter()
        self._sleep = sleep

    def available_modes(self) -> list[str]:
        return sorted(mode.value for mode in self._transports)

    def transport_for(self, mode: ExecutionMode) -> ExecutionTransport:
        transport = self._transports.get(mode)
        if transport is None:
            raise ModeUnavailableError(
                f"no transport registered for execution mode '{mode.value}'"
            )
        return transport

    async def place_with_retry(
        self, order: Order, market_price: float | None
    ) -> tuple[ExecutionReport, int]:
        """Place ``order`` on its mode's transport, retrying transient
        failures with exponential backoff. Returns (report, attempts)."""
        transport = self.transport_for(order.execution_mode)

        async def attempt() -> ExecutionReport:
            return await transport.place_order(order, market_price)

        return await retry_with_backoff(
            attempt,
            max_attempts=self._max_attempts,
            base_delay=self._base_delay,
            max_delay=self._max_delay,
            jitter=self._jitter,
            sleep=self._sleep,
        )

    async def cancel(
        self, mode: ExecutionMode, order_id: str, *, broker: str, account_id: str
    ) -> bool:
        transport = self.transport_for(mode)
        return await transport.cancel_order(order_id, broker=broker, account_id=account_id)


def get_router() -> ExecutionRouter:
    """FastAPI dependency: the real transports (overridden with fakes in tests)."""
    transports: dict[ExecutionMode, ExecutionTransport] = {
        ExecutionMode.PAPER: PaperTransport()
    }
    if config.live_enabled():
        transports[ExecutionMode.LIVE] = LiveTransport()
    return ExecutionRouter(transports)
