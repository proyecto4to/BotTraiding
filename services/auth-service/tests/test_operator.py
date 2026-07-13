"""Single-operator security: bootstrap, username login, IP lockout, change pw."""

from __future__ import annotations

import os

import pytest

from app import db as db_module
from app import security
from app.operator import bootstrap_operator
from app.throttle import LoginThrottle


# --- throttle (unit) ---------------------------------------------------------


def test_throttle_blocks_after_max_attempts():
    t = LoginThrottle(max_attempts=3, window_seconds=600, block_seconds=1800)
    assert not t.is_blocked("1.2.3.4")
    t.record_failure("1.2.3.4")
    t.record_failure("1.2.3.4")
    assert not t.is_blocked("1.2.3.4")  # below threshold
    t.record_failure("1.2.3.4")
    assert t.is_blocked("1.2.3.4")
    assert t.retry_after("1.2.3.4") > 0


def test_throttle_reset_clears_block():
    t = LoginThrottle(max_attempts=2, window_seconds=600, block_seconds=1800)
    t.record_failure("9.9.9.9")
    t.record_failure("9.9.9.9")
    assert t.is_blocked("9.9.9.9")
    t.reset("9.9.9.9")
    assert not t.is_blocked("9.9.9.9")


def test_throttle_is_per_ip():
    t = LoginThrottle(max_attempts=1, window_seconds=600, block_seconds=1800)
    t.record_failure("1.1.1.1")
    assert t.is_blocked("1.1.1.1")
    assert not t.is_blocked("2.2.2.2")


# --- operator bootstrap ------------------------------------------------------


@pytest.fixture()
def operator_env(monkeypatch):
    """Configure and create the operator; returns (username, password)."""
    username, password = "BlasJon", "OperatorPass1"
    monkeypatch.setenv("OPERATOR_USERNAME", username)
    monkeypatch.setenv("OPERATOR_PASSWORD_HASH", security.hash_password(password))
    with db_module.SessionLocal() as session:
        bootstrap_operator(session)
    return username, password


def test_bootstrap_creates_operator_with_admin_role(operator_env, client):
    username, password = operator_env
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == username
    assert "admin" in body["roles"]


def test_bootstrap_is_idempotent(operator_env):
    with db_module.SessionLocal() as session:
        bootstrap_operator(session)  # second run must not duplicate/raise
    from sqlalchemy import func, select

    from app.models import User

    with db_module.SessionLocal() as session:
        count = session.scalar(select(func.count()).select_from(User).where(User.username == "BlasJon"))
    assert count == 1


# --- username login ----------------------------------------------------------


def test_login_by_username_wrong_password_is_401(operator_env, client):
    username, _ = operator_env
    resp = client.post("/auth/login", json={"username": username, "password": "wrong"})
    assert resp.status_code == 401


def test_login_requires_an_identifier(client):
    resp = client.post("/auth/login", json={"password": "whatever"})
    assert resp.status_code == 422  # neither email nor username


# --- IP lockout via the endpoint ---------------------------------------------


def test_repeated_failures_lock_the_ip(operator_env, client):
    username, _ = operator_env
    for _ in range(5):
        bad = client.post("/auth/login", json={"username": username, "password": "nope"})
        assert bad.status_code == 401

    blocked = client.post("/auth/login", json={"username": username, "password": "nope"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers

    # Even the correct password is refused while the IP is blocked.
    correct = client.post(
        "/auth/login", json={"username": username, "password": operator_env[1]}
    )
    assert correct.status_code == 429


# --- change password ---------------------------------------------------------


def _register_and_login(client, email="user@gmail.com", password="Password123"):
    client.post("/auth/register", json={"email": email, "password": password})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    return resp.json()["access_token"]


def test_change_password_success_and_reauth(client):
    token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/auth/change_password",
        json={"current_password": "Password123", "new_password": "NewPassword456"},
        headers=headers,
    )
    assert resp.status_code == 200

    # Old password no longer works; new one does.
    old = client.post("/auth/login", json={"email": "user@gmail.com", "password": "Password123"})
    assert old.status_code == 401
    new = client.post("/auth/login", json={"email": "user@gmail.com", "password": "NewPassword456"})
    assert new.status_code == 200


def test_change_password_wrong_current_is_401(client):
    token = _register_and_login(client)
    resp = client.post(
        "/auth/change_password",
        json={"current_password": "WRONG", "new_password": "NewPassword456"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


def test_change_password_requires_auth(client):
    resp = client.post(
        "/auth/change_password",
        json={"current_password": "x", "new_password": "NewPassword456"},
    )
    assert resp.status_code == 401
