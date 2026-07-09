"""Alpaca connector (REST, trading API)."""

from __future__ import annotations

from .http_base import BaseHTTPConnector


class AlpacaConnector(BaseHTTPConnector):
    broker_name = "alpaca"
    demo_base_url = "https://paper-api.alpaca.markets/v2"
    real_base_url = "https://api.alpaca.markets/v2"

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.config.api_key:
            headers["APCA-API-KEY-ID"] = self.config.api_key
        if self.config.api_secret:
            headers["APCA-API-SECRET-KEY"] = self.config.api_secret
        return headers
