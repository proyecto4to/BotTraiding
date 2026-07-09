"""Async client for portfolio-engine, injectable via FastAPI dependency.

/risk/validate fetches the live portfolio snapshot through this client
(PORTFOLIO_ENGINE_URL). Tests override `get_portfolio_client` in
app.dependency_overrides; an inline portfolio_state in the request bypasses
the fetch entirely.
"""

from __future__ import annotations

import os

import httpx

from app.schemas import PortfolioStateIn

DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("PORTFOLIO_ENGINE_TIMEOUT", "5"))


class PortfolioUnavailableError(Exception):
    """portfolio-engine could not be reached or returned an error."""


class PortfolioClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (
            base_url
            or os.environ.get("PORTFOLIO_ENGINE_URL")
            or "http://portfolio-engine:8000"
        ).rstrip("/")

    async def get_state(self, account_id: str) -> PortfolioStateIn:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url, timeout=DEFAULT_TIMEOUT_SECONDS
            ) as client:
                response = await client.get(f"/portfolio/{account_id}")
                response.raise_for_status()
                return PortfolioStateIn.model_validate(response.json())
        except PortfolioUnavailableError:
            raise
        except Exception as exc:  # httpx errors, validation errors
            raise PortfolioUnavailableError(str(exc)) from exc


def get_portfolio_client() -> PortfolioClient:
    return PortfolioClient()
