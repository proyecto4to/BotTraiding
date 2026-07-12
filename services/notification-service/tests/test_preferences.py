"""Preferences CRUD + auth gates (own or admin)."""

from __future__ import annotations

import uuid

from tests.conftest import auth_headers

PREFS = {
    "subjects": ["risk.>", "execution.live_order"],
    "account_ids": ["acc-1"],
    "email_enabled": True,
    "email_address": "trader@example.com",
    "email_min_severity": "warning",
    "telegram_enabled": True,
    "telegram_chat_id": "chat-9",
    "telegram_min_severity": "critical",
    "webhook_enabled": False,
    "webhook_url": None,
    "webhook_secret": None,
    "webhook_min_severity": "info",
}


def test_requires_auth(client) -> None:
    assert client.get("/preferences/u1").status_code == 401
    assert client.put("/preferences/u1", json=PREFS).status_code == 401


def test_get_returns_defaults_when_unset(client) -> None:
    user = str(uuid.uuid4())
    response = client.get(f"/preferences/{user}", headers=auth_headers(["trader"], sub=user))
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user
    assert body["email_enabled"] is False
    assert body["subjects"] == []


def test_put_then_get_roundtrip(client) -> None:
    user = str(uuid.uuid4())
    headers = auth_headers(["trader"], sub=user)

    put = client.put(f"/preferences/{user}", json=PREFS, headers=headers)
    assert put.status_code == 200
    assert put.json()["email_min_severity"] == "warning"

    got = client.get(f"/preferences/{user}", headers=headers).json()
    for key, value in PREFS.items():
        assert got[key] == value

    # update in place (upsert path)
    updated = dict(PREFS, email_min_severity="critical")
    put2 = client.put(f"/preferences/{user}", json=updated, headers=headers)
    assert put2.status_code == 200
    assert put2.json()["email_min_severity"] == "critical"


def test_cannot_touch_other_users_preferences(client) -> None:
    me = auth_headers(["trader"], sub="user-a")
    assert client.get("/preferences/user-b", headers=me).status_code == 403
    assert client.put("/preferences/user-b", json=PREFS, headers=me).status_code == 403


def test_admin_can_manage_any_preferences(client, admin_headers) -> None:
    put = client.put("/preferences/user-b", json=PREFS, headers=admin_headers)
    assert put.status_code == 200
    got = client.get("/preferences/user-b", headers=admin_headers)
    assert got.status_code == 200
    assert got.json()["telegram_chat_id"] == "chat-9"


def test_put_validates_min_severity(client) -> None:
    user = "user-v"
    headers = auth_headers(["trader"], sub=user)
    bad = dict(PREFS, email_min_severity="loud")
    assert client.put(f"/preferences/{user}", json=bad, headers=headers).status_code == 422
