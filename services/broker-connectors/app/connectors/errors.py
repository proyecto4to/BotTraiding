"""Broker-agnostic connector error taxonomy.

Concrete connectors (Binance today, the other 7 as they get their real
integrations) raise subclasses of these so app/main.py and downstream
services (trading-engine) can react to *categories* (rejected order, rate
limited, clock skew...) without knowing broker-specific error codes.
"""

from __future__ import annotations

from typing import Optional


class ConnectorError(Exception):
    """Base class for every typed broker-connector failure."""


class OrderRejectedError(ConnectorError):
    """Order refused before or at the broker (exchange filters, bad params)."""


class InsufficientBalanceError(OrderRejectedError):
    """Order refused because the account lacks funds."""


class OrderNotFoundError(ConnectorError):
    """Referenced order does not exist / is no longer cancellable."""


class ClockSkewError(ConnectorError):
    """Local clock is outside the broker's accepted timestamp window."""


class UnsupportedTimeframeError(ConnectorError):
    """Requested timeframe has no equivalent interval at this broker."""


class ConnectorRateLimitError(ConnectorError):
    """Broker signalled rate limiting (HTTP 429/418 or equivalent)."""

    def __init__(self, message: str, retry_after_seconds: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
