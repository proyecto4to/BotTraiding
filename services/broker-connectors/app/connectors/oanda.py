"""OANDA connector (REST v20, FX/CFD)."""

from __future__ import annotations

from .http_base import BaseHTTPConnector


class OandaConnector(BaseHTTPConnector):
    broker_name = "oanda"
    demo_base_url = "https://api-fxpractice.oanda.com/v3"
    real_base_url = "https://api-fxtrade.oanda.com/v3"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.api_key}"} if self.config.api_key else {}
