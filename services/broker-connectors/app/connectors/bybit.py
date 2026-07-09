"""Bybit connector (REST, v5 unified account)."""

from __future__ import annotations

from .http_base import BaseHTTPConnector


class BybitConnector(BaseHTTPConnector):
    broker_name = "bybit"
    demo_base_url = "https://api-testnet.bybit.com"
    real_base_url = "https://api.bybit.com"

    def _auth_headers(self) -> dict[str, str]:
        return {"X-BAPI-API-KEY": self.config.api_key} if self.config.api_key else {}
