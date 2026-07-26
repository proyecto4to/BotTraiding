"""Async client that forwards ExecutionReports to portfolio-engine.

Architecture section 4: ExecutionReport -> PortfolioEngine.update(). The
forwarder POSTs the report (plus the symbol/side context the shared
contract does not carry) to POST /portfolio/{account_id}/executions.
Injectable FastAPI dependency; tests override get_portfolio_forwarder with
a recording fake. Forwarding failures are logged, never raised: a portfolio
outage must not lose the local execution record.
"""

from __future__ import annotations

import logging
import os

import httpx

from trading_contracts.auth import service_auth_header

from . import config

logger = logging.getLogger("execution-engine.portfolio")

SERVICE_NAME = "execution-engine"

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("PORTFOLIO_ENGINE_TIMEOUT", "5"))


class PortfolioForwarder:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url

    @property
    def base_url(self) -> str:
        return (self._base_url or config.portfolio_engine_url()).rstrip("/")

    async def forward(self, account_id: str, payload: dict) -> bool:
        """POST an ExecutionIngest payload; returns True when accepted."""
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=DEFAULT_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    f"/portfolio/{account_id}/executions",
                    json=payload,
                    headers=service_auth_header(SERVICE_NAME),
                )
                response.raise_for_status()
                return True
        except Exception as exc:  # httpx errors, HTTP errors
            logger.warning(
                "could not forward execution %s to portfolio-engine: %s",
                payload.get("order_id"),
                exc,
            )
            return False


def get_portfolio_forwarder() -> PortfolioForwarder:
    return PortfolioForwarder()
