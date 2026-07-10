"""ExecutionTransport protocol + the two HTTP implementations.

Architecture section 10: paper and live differ ONLY in execution_mode. Both
transports satisfy the same protocol, so the execution pipeline is a single
code path; mode is data that selects a transport in the ExecutionRouter,
never an if/else scattered through the pipeline.

- PaperTransport  -> paper-trading service   (POST /paper/orders, .../cancel)
- LiveTransport   -> broker-connectors service (POST /connectors/{broker}/orders)

Error mapping: network failures, 5xx and 409 (broker not connected yet)
raise TransientTransportError (retried with backoff); other 4xx raise
PermanentTransportError (no retry).
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

import httpx

from trading_contracts import ExecutionMode, ExecutionReport, Order

from . import config
from .retry import PermanentTransportError, TransientTransportError

logger = logging.getLogger("execution-engine.transports")

TRANSIENT_STATUS_CODES = {409, 500, 502, 503, 504}


@runtime_checkable
class ExecutionTransport(Protocol):
    """What the execution pipeline needs from any execution venue."""

    mode: ExecutionMode
    name: str

    async def place_order(
        self, order: Order, market_price: float | None
    ) -> ExecutionReport: ...

    async def cancel_order(
        self, order_id: str, *, broker: str, account_id: str
    ) -> bool: ...


async def _post_json(url: str, payload: dict) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=config.transport_timeout()) as client:
            return await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise TransientTransportError(f"transport unreachable: {exc}") from exc


def _raise_for_status(response: httpx.Response, transport_name: str) -> None:
    if response.status_code < 400:
        return
    detail = response.text[:500]
    if response.status_code in TRANSIENT_STATUS_CODES:
        raise TransientTransportError(
            f"{transport_name} returned {response.status_code}: {detail}"
        )
    raise PermanentTransportError(
        f"{transport_name} returned {response.status_code}: {detail}"
    )


class PaperTransport:
    """Routes orders to the paper-trading simulated broker."""

    mode = ExecutionMode.PAPER
    name = "paper-trading"

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url

    @property
    def base_url(self) -> str:
        return (self._base_url or config.paper_trading_url()).rstrip("/")

    async def place_order(self, order: Order, market_price: float | None) -> ExecutionReport:
        price = market_price if market_price is not None else order.price
        if price is None:
            raise PermanentTransportError(
                "paper execution requires a market price (order.price or request.market_price)"
            )
        payload = {
            "order_id": str(order.id),
            "signal_id": str(order.signal_id),
            "account_id": order.account_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "order_type": order.order_type.value,
            "price": price,
        }
        response = await _post_json(f"{self.base_url}/paper/orders", payload)
        _raise_for_status(response, self.name)
        return ExecutionReport.model_validate(response.json())

    async def cancel_order(self, order_id: str, *, broker: str, account_id: str) -> bool:
        try:
            response = await _post_json(
                f"{self.base_url}/paper/orders/{order_id}/cancel", {}
            )
        except TransientTransportError as exc:
            logger.warning("paper cancel of %s failed: %s", order_id, exc)
            return False
        return response.status_code < 400


class LiveTransport:
    """Routes orders to real brokers through the broker-connectors service."""

    mode = ExecutionMode.LIVE
    name = "broker-connectors"

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url

    @property
    def base_url(self) -> str:
        return (self._base_url or config.broker_connectors_url()).rstrip("/")

    async def place_order(self, order: Order, market_price: float | None) -> ExecutionReport:
        payload = {
            "id": str(order.id),
            "signal_id": str(order.signal_id),
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "order_type": order.order_type.value,
            "price": order.price,
            "account_id": order.account_id,
            "execution_mode": order.execution_mode.value,
        }
        response = await _post_json(
            f"{self.base_url}/connectors/{order.broker}/orders", payload
        )
        _raise_for_status(response, self.name)
        return ExecutionReport.model_validate(response.json())

    async def cancel_order(self, order_id: str, *, broker: str, account_id: str) -> bool:
        # TODO(broker-connectors): the service does not expose a cancel
        # endpoint yet (the BrokerConnector contract has cancel_order but no
        # REST route). Best effort: call the future route; a 404/failure is
        # reported as not-cancelled-at-broker while the child is still marked
        # cancelled locally.
        try:
            response = await _post_json(
                f"{self.base_url}/connectors/{broker}/orders/{order_id}/cancel",
                {"account_id": account_id},
            )
        except TransientTransportError as exc:
            logger.warning("live cancel of %s failed: %s", order_id, exc)
            return False
        return response.status_code < 400
