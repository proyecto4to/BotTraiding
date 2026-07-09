"""Per-user market activation via /config/me/markets."""

from __future__ import annotations

from tests.conftest import auth_headers


def test_me_markets_requires_auth(client, seeded_markets) -> None:
    assert client.get("/config/me/markets").status_code == 401
    assert client.put("/config/me/markets", json=[]).status_code == 401


def test_me_markets_defaults_follow_global_flag(client, seeded_markets) -> None:
    response = client.get("/config/me/markets", headers=auth_headers(sub="user-1"))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 9
    assert all(entry["user_enabled"] is True for entry in body)
    assert all(entry["effective_enabled"] is True for entry in body)


def test_user_can_disable_market_for_themselves(client, seeded_markets) -> None:
    crypto_id = seeded_markets["CRYPTO"].id
    headers = auth_headers(sub="user-1", roles=["trader"])

    response = client.put(
        "/config/me/markets",
        json=[{"market_id": crypto_id, "enabled": False}],
        headers=headers,
    )
    assert response.status_code == 200
    crypto = next(e for e in response.json() if e["market_id"] == crypto_id)
    assert crypto["user_enabled"] is False
    assert crypto["effective_enabled"] is False
    assert crypto["market_enabled"] is True  # global flag untouched

    # persisted: GET returns the same view
    body = client.get("/config/me/markets", headers=headers).json()
    crypto = next(e for e in body if e["market_id"] == crypto_id)
    assert crypto["user_enabled"] is False


def test_user_settings_are_per_user(client, seeded_markets) -> None:
    crypto_id = seeded_markets["CRYPTO"].id
    client.put(
        "/config/me/markets",
        json=[{"market_id": crypto_id, "enabled": False}],
        headers=auth_headers(sub="user-1"),
    )

    other = client.get("/config/me/markets", headers=auth_headers(sub="user-2")).json()
    crypto = next(e for e in other if e["market_id"] == crypto_id)
    assert crypto["user_enabled"] is True


def test_put_is_upsert_and_reenables(client, seeded_markets) -> None:
    crypto_id = seeded_markets["CRYPTO"].id
    headers = auth_headers(sub="user-1")

    client.put(
        "/config/me/markets",
        json=[{"market_id": crypto_id, "enabled": False}],
        headers=headers,
    )
    response = client.put(
        "/config/me/markets",
        json=[{"market_id": crypto_id, "enabled": True}],
        headers=headers,
    )
    crypto = next(e for e in response.json() if e["market_id"] == crypto_id)
    assert crypto["user_enabled"] is True
    assert crypto["effective_enabled"] is True


def test_globally_disabled_market_wins_over_user_enable(client, seeded_markets) -> None:
    crypto_id = seeded_markets["CRYPTO"].id
    client.patch(
        f"/config/markets/{crypto_id}",
        json={"enabled": False},
        headers=auth_headers(sub="admin-1", roles=["admin"]),
    )

    headers = auth_headers(sub="user-1")
    response = client.put(
        "/config/me/markets",
        json=[{"market_id": crypto_id, "enabled": True}],
        headers=headers,
    )
    crypto = next(e for e in response.json() if e["market_id"] == crypto_id)
    assert crypto["market_enabled"] is False
    assert crypto["user_enabled"] is True
    assert crypto["effective_enabled"] is False


def test_put_unknown_market_404(client, seeded_markets) -> None:
    response = client.put(
        "/config/me/markets",
        json=[{"market_id": "00000000-0000-0000-0000-000000000000", "enabled": False}],
        headers=auth_headers(),
    )
    assert response.status_code == 404
