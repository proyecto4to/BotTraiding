"""Liveness/readiness probes."""

from __future__ import annotations


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "market-data"}


def test_ready(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"
