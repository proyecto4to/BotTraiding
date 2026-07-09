"""Register, login (success/failure), refresh, logout."""

from __future__ import annotations


def _register(client, email="user@example.com", password="supersecret1"):
    return client.post("/auth/register", json={"email": email, "password": password})


def test_register_creates_user_with_default_role(client) -> None:
    resp = _register(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "user@example.com"
    assert body["roles"] == ["viewer"]
    assert body["mfa_enabled"] is False


def test_register_duplicate_email_conflicts(client) -> None:
    _register(client)
    resp = _register(client)
    assert resp.status_code == 409


def test_login_success_returns_token_pair(client) -> None:
    _register(client)
    resp = client.post("/auth/login", json={"email": "user@example.com", "password": "supersecret1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["mfa_required"] is False


def test_login_failure_wrong_password(client) -> None:
    _register(client)
    resp = client.post("/auth/login", json={"email": "user@example.com", "password": "wrongpass"})
    assert resp.status_code == 401


def test_login_failure_unknown_user(client) -> None:
    resp = client.post("/auth/login", json={"email": "nope@example.com", "password": "whatever1"})
    assert resp.status_code == 401


def test_refresh_issues_new_access_token(client) -> None:
    _register(client)
    login = client.post("/auth/login", json={"email": "user@example.com", "password": "supersecret1"}).json()
    resp = client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_logout_revokes_refresh_token(client) -> None:
    _register(client)
    login = client.post("/auth/login", json={"email": "user@example.com", "password": "supersecret1"}).json()
    logout_resp = client.post("/auth/logout", json={"refresh_token": login["refresh_token"]})
    assert logout_resp.status_code == 204

    resp = client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert resp.status_code == 401


def test_me_requires_auth(client) -> None:
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_me_returns_current_user(client) -> None:
    _register(client)
    login = client.post("/auth/login", json={"email": "user@example.com", "password": "supersecret1"}).json()
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {login['access_token']}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "user@example.com"
