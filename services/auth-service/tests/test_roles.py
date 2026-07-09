"""Role assignment + require_role rejection."""

from __future__ import annotations


def _register_and_login(client, email, password="supersecret1"):
    client.post("/auth/register", json={"email": email, "password": password})
    return client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]


def _make_admin(client, user_id: str) -> None:
    """Bootstrap: directly promote a user to admin via the DB session used by
    the app, since there's no admin yet to call the assign-role endpoint."""
    from app.db import SessionLocal
    from app.models import Role, User, UserRole

    db = SessionLocal()
    try:
        role = db.query(Role).filter_by(name="admin").first()
        if role is None:
            role = Role(name="admin")
            db.add(role)
            db.commit()
            db.refresh(role)
        db.add(UserRole(user_id=user_id, role_id=role.id))
        db.commit()
    finally:
        db.close()


def test_require_role_rejects_non_admin(client) -> None:
    token = _register_and_login(client, "plain@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/auth/users/someone/roles", json={"role": "trader", "action": "assign"}, headers=headers)
    assert resp.status_code == 403


def test_admin_can_assign_and_revoke_role(client) -> None:
    admin_token = _register_and_login(client, "admin@example.com")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    admin_me = client.get("/auth/me", headers=admin_headers).json()
    _make_admin(client, admin_me["id"])

    # re-login to get a token with the admin role claim refreshed
    admin_token = client.post(
        "/auth/login", json={"email": "admin@example.com", "password": "supersecret1"}
    ).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    target_token = _register_and_login(client, "target@example.com")
    target_id = client.get("/auth/me", headers={"Authorization": f"Bearer {target_token}"}).json()["id"]

    assign_resp = client.post(
        f"/auth/users/{target_id}/roles", json={"role": "trader", "action": "assign"}, headers=admin_headers
    )
    assert assign_resp.status_code == 200
    assert "trader" in assign_resp.json()["roles"]

    revoke_resp = client.post(
        f"/auth/users/{target_id}/roles", json={"role": "trader", "action": "revoke"}, headers=admin_headers
    )
    assert revoke_resp.status_code == 200
    assert "trader" not in revoke_resp.json()["roles"]


def test_assign_unknown_role_rejected(client) -> None:
    admin_token = _register_and_login(client, "admin2@example.com")
    admin_me = client.get("/auth/me", headers={"Authorization": f"Bearer {admin_token}"}).json()
    _make_admin(client, admin_me["id"])
    admin_token = client.post(
        "/auth/login", json={"email": "admin2@example.com", "password": "supersecret1"}
    ).json()["access_token"]

    resp = client.post(
        f"/auth/users/{admin_me['id']}/roles",
        json={"role": "not-a-role", "action": "assign"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400
