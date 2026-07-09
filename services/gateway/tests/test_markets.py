"""Market config API: listing, enable/disable, RBAC enforcement."""

from __future__ import annotations

from tests.conftest import auth_headers


def test_list_markets_requires_auth(client, seeded_markets) -> None:
    response = client.get("/config/markets")
    assert response.status_code == 401


def test_list_markets_rejects_invalid_token(client, seeded_markets) -> None:
    response = client.get(
        "/config/markets", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


def test_list_markets_rejects_expired_token(client, seeded_markets) -> None:
    response = client.get("/config/markets", headers=auth_headers(expired=True))
    assert response.status_code == 401


def test_list_markets_returns_all_nine_categories(client, seeded_markets) -> None:
    response = client.get("/config/markets", headers=auth_headers(roles=["viewer"]))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 9
    codes = {market["code"] for market in body}
    assert codes == {
        "STOCKS", "ETFS", "FOREX", "CRYPTO", "FUTURES",
        "OPTIONS", "COMMODITIES", "BONDS", "INDICES",
    }
    assert all(market["enabled"] is True for market in body)
    assert all(isinstance(market["trading_hours"], dict) for market in body)


def test_admin_can_disable_and_reenable_market(client, seeded_markets) -> None:
    market_id = seeded_markets["CRYPTO"].id
    headers = auth_headers(sub="admin-1", roles=["admin"])

    response = client.patch(
        f"/config/markets/{market_id}", json={"enabled": False}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    listed = client.get("/config/markets", headers=headers).json()
    crypto = next(market for market in listed if market["code"] == "CRYPTO")
    assert crypto["enabled"] is False

    response = client.patch(
        f"/config/markets/{market_id}", json={"enabled": True}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is True


def test_admin_can_update_trading_hours(client, seeded_markets) -> None:
    market_id = seeded_markets["FOREX"].id
    new_hours = {"timezone": "UTC", "sessions": []}
    response = client.patch(
        f"/config/markets/{market_id}",
        json={"trading_hours": new_hours},
        headers=auth_headers(roles=["admin"]),
    )
    assert response.status_code == 200
    assert response.json()["trading_hours"] == new_hours


def test_non_admin_cannot_patch_market(client, seeded_markets) -> None:
    market_id = seeded_markets["CRYPTO"].id
    for roles in (["trader"], ["viewer"], ["auditor"], []):
        response = client.patch(
            f"/config/markets/{market_id}",
            json={"enabled": False},
            headers=auth_headers(roles=roles),
        )
        assert response.status_code == 403, roles


def test_patch_market_requires_token(client, seeded_markets) -> None:
    market_id = seeded_markets["CRYPTO"].id
    response = client.patch(f"/config/markets/{market_id}", json={"enabled": False})
    assert response.status_code == 401


def test_patch_unknown_market_is_404(client, seeded_markets) -> None:
    response = client.patch(
        "/config/markets/00000000-0000-0000-0000-000000000000",
        json={"enabled": False},
        headers=auth_headers(roles=["admin"]),
    )
    assert response.status_code == 404


def test_mfa_pending_token_is_rejected(client, seeded_markets) -> None:
    response = client.get(
        "/config/markets", headers=auth_headers(roles=["admin"], mfa_pending=True)
    )
    assert response.status_code == 401


def test_refresh_token_is_rejected(client, seeded_markets) -> None:
    response = client.get(
        "/config/markets", headers=auth_headers(token_type="refresh")
    )
    assert response.status_code == 401
