"""Binance connector (REST, spot). Demo maps to Binance Testnet."""

from __future__ import annotations

from .http_base import BaseHTTPConnector


class BinanceConnector(BaseHTTPConnector):
    broker_name = "binance"
    demo_base_url = "https://testnet.binance.vision/api/v3"
    real_base_url = "https://api.binance.com/api/v3"

    def _auth_headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self.config.api_key} if self.config.api_key else {}
