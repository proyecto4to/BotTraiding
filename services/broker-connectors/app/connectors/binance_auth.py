"""HMAC-SHA256 request signing for Binance SIGNED endpoints.

Binance spec (https://developers.binance.com/docs/binance-spot-api-docs):
SIGNED endpoints require a ``timestamp`` (ms) parameter, accept an optional
``recvWindow`` (ms, default 5000), and a ``signature`` parameter that is the
lowercase hex HMAC-SHA256 of the *exact* query string (and/or request body)
using the API secret as key. The API key itself travels in the
``X-MBX-APIKEY`` header, never in the signed payload.

Kept transport-free so it is trivially unit-testable against the fixture
published in the Binance docs (see tests/test_binance_auth.py).
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Mapping
from urllib.parse import urlencode

DEFAULT_RECV_WINDOW_MS = 5000


def sign_payload(payload: str, api_secret: str) -> str:
    """Return the lowercase hex HMAC-SHA256 of ``payload`` keyed by ``api_secret``."""
    return hmac.new(api_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def build_query(params: Mapping[str, Any]) -> str:
    """Serialize params (skipping ``None`` values) preserving insertion order.

    Binance verifies the signature against the exact string sent, so the
    caller must transmit this identical string - never let the HTTP client
    re-encode/re-order it.
    """
    items = [(key, value) for key, value in params.items() if value is not None]
    return urlencode(items)


def signed_query(
    params: Mapping[str, Any],
    api_secret: str,
    *,
    timestamp_ms: int,
    recv_window_ms: int = DEFAULT_RECV_WINDOW_MS,
) -> str:
    """Build the full query string for a SIGNED endpoint.

    Appends ``recvWindow`` and ``timestamp`` after the business params (the
    ordering used in the Binance docs example) and finally the ``signature``
    computed over everything before it.
    """
    base_params: dict[str, Any] = {key: value for key, value in params.items() if value is not None}
    base_params["recvWindow"] = recv_window_ms
    base_params["timestamp"] = timestamp_ms
    query = build_query(base_params)
    return f"{query}&signature={sign_payload(query, api_secret)}"


def auth_headers(api_key: str) -> dict[str, str]:
    """Binance authenticates the key via header; the signature covers params only."""
    return {"X-MBX-APIKEY": api_key} if api_key else {}
