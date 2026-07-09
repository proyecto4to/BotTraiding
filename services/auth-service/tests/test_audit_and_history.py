"""Audit log pagination + own history endpoint."""

from __future__ import annotations

from app.models import Role, UserRole


def _register_and_login(client, email, password="supersecret1"):
    client.post("/auth/register", json={"email": email, "password": password})
    return client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]


def _promote(user_id: str, role_name: str) -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        role = db.query(Role).filter_by(name=role_name).first()
        if role is None:
            role = Role(name=role_name)
            db.add(role)
            db.commit()
            db.refresh(role)
        db.add(UserRole(user_id=user_id, role_id=role.id))
        db.commit()
    finally:
        db.close()


def test_audit_requires_admin_or_auditor(client) -> None:
    token = _register_and_login(client, "plain@example.com")
    resp = client.get("/auth/audit", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_audit_lists_with_pagination(client) -> None:
    token = _register_and_login(client, "auditor@example.com")
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    _promote(me["id"], "auditor")
    token = client.post(
        "/auth/login", json={"email": "auditor@example.com", "password": "supersecret1"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # generate a few more audit entries
    _register_and_login(client, "other1@example.com")
    _register_and_login(client, "other2@example.com")

    resp = client.get("/auth/audit?limit=2&offset=0", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["total"] >= 5  # registers + logins recorded so far
    assert body["limit"] == 2


def test_audit_filters_by_action(client) -> None:
    token = _register_and_login(client, "auditor2@example.com")
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    _promote(me["id"], "auditor")
    token = client.post(
        "/auth/login", json={"email": "auditor2@example.com", "password": "supersecret1"}
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/auth/audit?action=register", headers=headers)
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["action"] == "register"


def test_my_history_returns_own_entries_only(client) -> None:
    token = _register_and_login(client, "hist@example.com")
    resp = client.get("/auth/me/history", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2  # register + login
    for item in body["items"]:
        assert item["actor"]  # each entry has an actor recorded
