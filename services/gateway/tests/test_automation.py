"""Master switch (P8): /api/automation proxies to the autonomy-controller.

Auth is enforced at the gateway (view = any user, toggle = admin) and the
endpoints degrade gracefully when the controller is unreachable — in tests the
controller URL points nowhere, so every call exercises the down path.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("AUTONOMY_URL", "http://127.0.0.1:59999")

from .conftest import auth_headers


def test_state_requires_authentication(client):
    assert client.get("/api/automation/state").status_code == 401


def test_state_degrades_when_controller_down(client):
    resp = client.get("/api/automation/state", headers=auth_headers(roles=["viewer"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["mode"] == "unavailable"


def test_toggle_requires_admin(client):
    assert client.post("/api/automation/toggle").status_code == 401
    forbidden = client.post("/api/automation/toggle", headers=auth_headers(roles=["trader"]))
    assert forbidden.status_code == 403


def test_toggle_admin_degrades_when_controller_down(client):
    resp = client.post("/api/automation/toggle", headers=auth_headers(roles=["admin"]))
    # Admin passes the gate; controller is down -> graceful degraded payload.
    assert resp.status_code == 200
    assert resp.json()["mode"] == "unavailable"


def test_decisions_requires_auth_and_degrades(client):
    assert client.get("/api/automation/decisions").status_code == 401
    resp = client.get("/api/automation/decisions", headers=auth_headers(roles=["viewer"]))
    assert resp.status_code == 200
    assert resp.json() == []  # controller down -> empty list
