"""OKX connector (REST v5). Demo/real share a host; OKX distinguishes demo
trading via the `x-simulated-trading` header rather than a separate URL."""

from __future__ import annotations

from .http_base import BaseHTTPConnector


class OkxConnector(BaseHTTPConnector):
    broker_name = "okx"
    demo_base_url = "https://www.okx.com"
    real_base_url = "https://www.okx.com"

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.config.api_key:
            headers["OK-ACCESS-KEY"] = self.config.api_key
        if self.config.demo:
            headers["x-simulated-trading"] = "1"
        return headers
