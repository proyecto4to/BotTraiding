"""Kraken connector (REST).

Kraken spot has no public sandbox; ``demo=True`` maps to Kraken Futures'
demo environment as the closest published sandbox. For spot "paper"
behaviour, pair this connector with ``execution_mode=paper`` upstream in
execution-engine rather than expecting Kraken itself to simulate fills.
"""

from __future__ import annotations

from .http_base import BaseHTTPConnector


class KrakenConnector(BaseHTTPConnector):
    broker_name = "kraken"
    demo_base_url = "https://demo-futures.kraken.com/derivatives/api/v3"
    real_base_url = "https://api.kraken.com/0"

    def _auth_headers(self) -> dict[str, str]:
        return {"API-Key": self.config.api_key} if self.config.api_key else {}
