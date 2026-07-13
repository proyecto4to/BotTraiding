"""Liveness/readiness probes."""

from __future__ import annotations


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "autonomy-controller"}


def test_ready(client):
    assert client.get("/ready").json()["status"] == "ready"
