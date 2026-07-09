"""MFA enable + verify + login-with-mfa flow."""

from __future__ import annotations

import pyotp


def _register_and_login(client, email="mfa@example.com", password="supersecret1"):
    client.post("/auth/register", json={"email": email, "password": password})
    login = client.post("/auth/login", json={"email": email, "password": password}).json()
    return login["access_token"]


def test_mfa_enable_verify_and_login(client) -> None:
    access_token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {access_token}"}

    enable_resp = client.post("/auth/mfa/enable", headers=headers)
    assert enable_resp.status_code == 200
    secret = enable_resp.json()["secret"]
    assert enable_resp.json()["provisioning_uri"].startswith("otpauth://")

    totp = pyotp.TOTP(secret)
    verify_resp = client.post("/auth/mfa/verify", json={"code": totp.now()}, headers=headers)
    assert verify_resp.status_code == 200
    assert verify_resp.json()["mfa_enabled"] is True

    # Subsequent login should now require MFA.
    login_resp = client.post("/auth/login", json={"email": "mfa@example.com", "password": "supersecret1"})
    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body["mfa_required"] is True
    assert body["mfa_pending_token"]
    assert body["access_token"] is None

    mfa_login = client.post(
        "/auth/login/mfa",
        json={"mfa_pending_token": body["mfa_pending_token"], "code": totp.now()},
    )
    assert mfa_login.status_code == 200
    assert mfa_login.json()["access_token"]


def test_mfa_login_rejects_bad_code(client) -> None:
    access_token = _register_and_login(client)
    headers = {"Authorization": f"Bearer {access_token}"}
    secret = client.post("/auth/mfa/enable", headers=headers).json()["secret"]
    totp = pyotp.TOTP(secret)
    client.post("/auth/mfa/verify", json={"code": totp.now()}, headers=headers)

    login_resp = client.post("/auth/login", json={"email": "mfa@example.com", "password": "supersecret1"})
    pending_token = login_resp.json()["mfa_pending_token"]

    resp = client.post("/auth/login/mfa", json={"mfa_pending_token": pending_token, "code": "000000"})
    assert resp.status_code == 401
