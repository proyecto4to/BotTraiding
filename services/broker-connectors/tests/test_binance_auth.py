"""Signature tests against the fixture published in the Binance API docs.

Fixture source: Binance spot API documentation, "SIGNED Endpoint Examples
for POST /api/v3/order" (Example 1: as a request body / query string).
"""

from __future__ import annotations

from app.connectors import binance_auth

# Documented example credentials (public fixture, not real keys).
DOCS_API_KEY = "vmPUZE6mv9SD5VNHk4HlWFsOr6aKE2zvsw0MuIgwCIPy6utIco14y7Ju91duEh8A"
DOCS_API_SECRET = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
DOCS_QUERY = (
    "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC"
    "&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
)
DOCS_SIGNATURE = "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


def test_signature_matches_binance_docs_fixture():
    assert binance_auth.sign_payload(DOCS_QUERY, DOCS_API_SECRET) == DOCS_SIGNATURE


def test_signed_query_reproduces_docs_example_end_to_end():
    """Building the query from params must yield the exact documented string
    (business params, then recvWindow, then timestamp, then signature)."""
    params = {
        "symbol": "LTCBTC",
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": 1,
        "price": 0.1,
    }
    query = binance_auth.signed_query(
        params, DOCS_API_SECRET, timestamp_ms=1499827319559, recv_window_ms=5000
    )
    assert query == f"{DOCS_QUERY}&signature={DOCS_SIGNATURE}"


def test_signed_query_skips_none_values():
    query = binance_auth.signed_query(
        {"symbol": "BTCUSDT", "price": None}, "secret", timestamp_ms=1700000000000
    )
    assert "price" not in query
    assert query.startswith("symbol=BTCUSDT&recvWindow=5000&timestamp=1700000000000&signature=")


def test_auth_headers_carry_api_key_only_when_present():
    assert binance_auth.auth_headers(DOCS_API_KEY) == {"X-MBX-APIKEY": DOCS_API_KEY}
    assert binance_auth.auth_headers("") == {}
