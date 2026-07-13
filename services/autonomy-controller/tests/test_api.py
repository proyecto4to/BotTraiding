"""API: control endpoints, auth gates, tick and decisions."""

from __future__ import annotations


def test_state_starts_off(client):
    resp = client.get("/autonomy/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "OFF"
    assert body["enabled"] is False


def test_enable_requires_admin(client, trader_headers):
    assert client.post("/autonomy/enable").status_code == 401
    assert client.post("/autonomy/enable", headers=trader_headers).status_code == 403


def test_enable_disable_flow(client, admin_headers):
    enabled = client.post("/autonomy/enable", headers=admin_headers)
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["state"] == "LEARNING"

    disabled = client.post("/autonomy/disable", headers=admin_headers)
    assert disabled.status_code == 200
    assert disabled.json()["state"] == "OFF"


def test_tick_runs_a_cycle_and_persists(client, admin_headers, fake_clients):
    client.post("/autonomy/enable", headers=admin_headers)
    tick = client.post("/autonomy/tick")
    assert tick.status_code == 200
    assert tick.json()["acted"] is True

    decisions = client.get("/autonomy/decisions").json()
    assert len(decisions) == 1
    assert decisions[0]["selection"][0]["strategy_key"] == "sma_crossover"


def test_tick_when_off_does_not_act(client, fake_clients):
    tick = client.post("/autonomy/tick")
    assert tick.status_code == 200
    assert tick.json()["acted"] is False
    assert fake_clients.trading.created == []


def test_halt_and_reset_flow(client, admin_headers):
    client.post("/autonomy/enable", headers=admin_headers)
    halted = client.post("/autonomy/halt", json={"reason": "kill"}, headers=admin_headers)
    assert halted.status_code == 200
    assert halted.json()["state"] == "HALTED"

    # Cannot enable from HALTED.
    assert client.post("/autonomy/enable", headers=admin_headers).status_code == 409

    reset = client.post("/autonomy/reset", headers=admin_headers)
    assert reset.status_code == 200
    assert reset.json()["state"] == "OFF"


def test_disable_stops_running_autonomy_bots(client, admin_headers, fake_clients):
    client.post("/autonomy/enable", headers=admin_headers)
    client.post("/autonomy/tick")  # creates + starts a bot
    assert any(b["status"] == "running" for b in fake_clients.trading.bots)

    client.post("/autonomy/disable", headers=admin_headers)
    assert all(b["status"] != "running" for b in fake_clients.trading.bots)
