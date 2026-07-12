"""POST /bots/{id}/run-once round-trip via TestClient: one synchronous
cycle with the DI clients, CycleReport returned AND persisted/queryable."""

from __future__ import annotations

from app.clients import get_clients
from app.main import app

from .conftest import (
    FakeClientsBundle,
    FakeRisk,
    FakeStrategy,
    make_bot_payload,
    make_signal,
)


def _create(client, headers, **overrides) -> dict:
    response = client.post("/bots", json=make_bot_payload(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_run_once_full_round_trip(client, trader_headers):
    signal = make_signal()
    clients = FakeClientsBundle(
        strategy=FakeStrategy({"sma_crossover": signal}),
        risk=FakeRisk(approved=True, max_size_allowed=3.0),
    )
    app.dependency_overrides[get_clients] = lambda: clients

    bot = _create(client, trader_headers)
    response = client.post(f"/bots/{bot['id']}/run-once", headers=trader_headers)
    assert response.status_code == 200, response.text
    report = response.json()

    assert report["bot_id"] == bot["id"]
    assert report["status"] == "ok"
    assert len(report["signals"]) == 1
    assert len(report["decisions"]) == 1
    assert len(report["orders"]) == 1
    assert report["orders"][0]["quantity"] == 3.0
    assert report["orders"][0]["status"] == "filled"

    # persisted and queryable through GET /bots/{id}/cycles
    cycles = client.get(f"/bots/{bot['id']}/cycles").json()
    assert len(cycles) == 1
    assert cycles[0]["id"] == report["id"]
    assert cycles[0]["orders"] == report["orders"]


def test_run_once_rejected_signal_no_order(client, trader_headers):
    signal = make_signal()
    clients = FakeClientsBundle(
        strategy=FakeStrategy({"sma_crossover": signal}),
        risk=FakeRisk(approved=False),
    )
    app.dependency_overrides[get_clients] = lambda: clients

    bot = _create(client, trader_headers)
    report = client.post(f"/bots/{bot['id']}/run-once", headers=trader_headers).json()
    assert report["orders"] == []
    assert report["decisions"][0]["approved"] is False
    assert clients.execution.submissions == []


def test_run_once_hard_halt_skips(client, trader_headers):
    clients = FakeClientsBundle(risk=FakeRisk(breaker_state="HARD_HALT"))
    app.dependency_overrides[get_clients] = lambda: clients

    bot = _create(client, trader_headers)
    report = client.post(f"/bots/{bot['id']}/run-once", headers=trader_headers).json()
    assert report["status"] == "skipped"
    assert "hard_halt" in (report["reason"] or "")
    assert clients.market_data.calls == []


def test_run_once_requires_auth_and_roles(client, trader_headers, admin_headers):
    clients = FakeClientsBundle()
    app.dependency_overrides[get_clients] = lambda: clients

    bot = _create(client, admin_headers, mode="live")
    assert client.post(f"/bots/{bot['id']}/run-once").status_code == 401
    assert (
        client.post(f"/bots/{bot['id']}/run-once", headers=trader_headers).status_code
        == 403
    )
    assert (
        client.post(f"/bots/{bot['id']}/run-once", headers=admin_headers).status_code
        == 200
    )


def test_run_once_conflicts_while_running(client, trader_headers, fake_clients):
    from app.orchestrator import runner

    app.dependency_overrides[get_clients] = lambda: fake_clients
    runner.clients_factory = lambda: fake_clients
    try:
        bot = _create(client, trader_headers)
        assert (
            client.post(f"/bots/{bot['id']}/start", headers=trader_headers).status_code
            == 200
        )
        response = client.post(f"/bots/{bot['id']}/run-once", headers=trader_headers)
        assert response.status_code == 409
        client.post(f"/bots/{bot['id']}/stop", headers=trader_headers)
    finally:
        runner.clients_factory = get_clients
