"""OAuth (Google) callback with mocked token exchange -- no real network call."""

from __future__ import annotations

import pytest

from app import oauth


def test_oauth_login_redirects_to_google(client) -> None:
    resp = client.get("/auth/oauth/google/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert "accounts.google.com" in resp.headers["location"]


def test_oauth_callback_creates_user_and_issues_tokens(client, monkeypatch) -> None:
    async def fake_exchange_code(code: str) -> dict:
        assert code == "fake-code"
        return {"email": "oauthuser@example.com", "provider_user_id": "google-sub-123"}

    monkeypatch.setattr(oauth, "exchange_code", fake_exchange_code)

    resp = client.get("/auth/oauth/google/callback?code=fake-code")
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "oauthuser@example.com"


def test_oauth_callback_links_existing_user_by_email(client, monkeypatch) -> None:
    client.post("/auth/register", json={"email": "existing@example.com", "password": "supersecret1"})

    async def fake_exchange_code(code: str) -> dict:
        return {"email": "existing@example.com", "provider_user_id": "google-sub-456"}

    monkeypatch.setattr(oauth, "exchange_code", fake_exchange_code)

    resp = client.get("/auth/oauth/google/callback?code=whatever")
    assert resp.status_code == 200

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {resp.json()['access_token']}"})
    assert me.json()["email"] == "existing@example.com"


def test_oauth_callback_failure_returns_400(client, monkeypatch) -> None:
    async def fake_exchange_code(code: str) -> dict:
        raise RuntimeError("token exchange failed")

    monkeypatch.setattr(oauth, "exchange_code", fake_exchange_code)

    resp = client.get("/auth/oauth/google/callback?code=bad")
    assert resp.status_code == 400
