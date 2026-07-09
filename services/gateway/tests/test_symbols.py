"""Symbol CRUD under /config/symbols and /config/markets/{id}/symbols."""

from __future__ import annotations

from tests.conftest import auth_headers

ADMIN = {"roles": ["admin"]}


def test_create_symbol_as_admin(client, seeded_markets) -> None:
    market_id = seeded_markets["CRYPTO"].id
    response = client.post(
        "/config/symbols",
        json={"market_id": market_id, "ticker": "SOLUSDT", "name": "Solana/USDT"},
        headers=auth_headers(**ADMIN),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["ticker"] == "SOLUSDT"
    assert body["market_id"] == market_id
    assert body["is_active"] is True


def test_create_symbol_requires_admin(client, seeded_markets) -> None:
    market_id = seeded_markets["CRYPTO"].id
    response = client.post(
        "/config/symbols",
        json={"market_id": market_id, "ticker": "SOLUSDT"},
        headers=auth_headers(roles=["trader"]),
    )
    assert response.status_code == 403


def test_create_symbol_unknown_market_404(client, seeded_markets) -> None:
    response = client.post(
        "/config/symbols",
        json={"market_id": "00000000-0000-0000-0000-000000000000", "ticker": "X"},
        headers=auth_headers(**ADMIN),
    )
    assert response.status_code == 404


def test_create_duplicate_ticker_conflict(client, seeded_markets, seeded_symbols) -> None:
    market_id = seeded_markets["CRYPTO"].id
    response = client.post(
        "/config/symbols",
        json={"market_id": market_id, "ticker": "BTCUSDT"},
        headers=auth_headers(**ADMIN),
    )
    assert response.status_code == 409


def test_same_ticker_allowed_in_different_market(client, seeded_markets, seeded_symbols) -> None:
    response = client.post(
        "/config/symbols",
        json={"market_id": seeded_markets["FUTURES"].id, "ticker": "BTCUSDT"},
        headers=auth_headers(**ADMIN),
    )
    assert response.status_code == 201


def test_list_symbols_and_market_filter(client, seeded_markets, seeded_symbols) -> None:
    headers = auth_headers(roles=["viewer"])

    response = client.get("/config/symbols", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 3

    crypto_id = seeded_markets["CRYPTO"].id
    response = client.get(f"/config/symbols?market_id={crypto_id}", headers=headers)
    assert response.status_code == 200
    tickers = [symbol["ticker"] for symbol in response.json()]
    assert tickers == ["BTCUSDT", "ETHUSDT"]


def test_list_symbols_requires_auth(client, seeded_symbols) -> None:
    assert client.get("/config/symbols").status_code == 401


def test_market_symbols_nested_endpoint(client, seeded_markets, seeded_symbols) -> None:
    stocks_id = seeded_markets["STOCKS"].id
    response = client.get(
        f"/config/markets/{stocks_id}/symbols", headers=auth_headers()
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["ticker"] == "AAPL"


def test_market_symbols_unknown_market_404(client, seeded_markets) -> None:
    response = client.get(
        "/config/markets/00000000-0000-0000-0000-000000000000/symbols",
        headers=auth_headers(),
    )
    assert response.status_code == 404


def test_patch_symbol_deactivates(client, seeded_symbols) -> None:
    symbol_id = seeded_symbols[0].id
    response = client.patch(
        f"/config/symbols/{symbol_id}",
        json={"is_active": False},
        headers=auth_headers(**ADMIN),
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_patch_symbol_requires_admin(client, seeded_symbols) -> None:
    symbol_id = seeded_symbols[0].id
    response = client.patch(
        f"/config/symbols/{symbol_id}",
        json={"is_active": False},
        headers=auth_headers(roles=["viewer"]),
    )
    assert response.status_code == 403


def test_patch_unknown_symbol_404(client, seeded_markets) -> None:
    response = client.patch(
        "/config/symbols/00000000-0000-0000-0000-000000000000",
        json={"is_active": False},
        headers=auth_headers(**ADMIN),
    )
    assert response.status_code == 404
