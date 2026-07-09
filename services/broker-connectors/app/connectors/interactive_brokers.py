"""Interactive Brokers connector.

Real IBKR integration typically runs against a locally-running TWS or IB
Gateway process, either via the socket-based TWS API (ib_insync/ibapi) or
the REST-style Client Portal Web API Gateway. This connector targets the
Client Portal Gateway shape so it fits the shared HTTP transport in
``http_base.py``; a socket-based TWS API integration would need its own
transport and is future work (also requires a running Gateway instance,
which this sandbox does not have).
"""

from __future__ import annotations

from .http_base import BaseHTTPConnector


class InteractiveBrokersConnector(BaseHTTPConnector):
    broker_name = "interactive_brokers"
    # IB Client Portal Gateway conventionally listens locally; paper vs live
    # is usually the same gateway with a paper account logged in, but we
    # expose distinct ports here for demo/real symmetry with other brokers.
    demo_base_url = "https://localhost:5001/v1/api"
    real_base_url = "https://localhost:5000/v1/api"

    def _auth_headers(self) -> dict[str, str]:
        # The Client Portal Gateway authenticates via an interactive browser
        # login + session cookie, not a static API key header. We forward
        # whatever bearer/session token the caller supplies.
        if self.config.api_key:
            return {"Authorization": f"Bearer {self.config.api_key}"}
        return {}
