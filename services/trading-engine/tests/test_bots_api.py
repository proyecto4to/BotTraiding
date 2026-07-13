"""Bot CRUD + lifecycle endpoints: role gates, status transitions,
config-only-when-stopped, cycle listing."""

from __future__ import annotations

from .conftest import make_bot_payload


def create_bot(client, headers, **overrides):
    response = client.post("/bots", json=make_bot_payload(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- create ---------------------------------------------------------------------


def test_create_requires_auth(client):
    assert client.post("/bots", json=make_bot_payload()).status_code == 401


def test_create_paper_bot_any_user(client, trader_headers):
    bot = create_bot(client, trader_headers)
    assert bot["status"] == "stopped"
    assert bot["execution_mode"] == "paper"
    assert bot["created_by"]


def test_create_live_bot_requires_admin(client, trader_headers, admin_headers):
    response = client.post(
        "/bots", json=make_bot_payload(mode="live"), headers=trader_headers
    )
    assert response.status_code == 403

    bot = create_bot(client, admin_headers, mode="live")
    assert bot["execution_mode"] == "live"


def test_create_rejects_bad_timeframe(client, trader_headers):
    payload = make_bot_payload()
    payload["timeframe"] = "sometimes"
    assert client.post("/bots", json=payload, headers=trader_headers).status_code == 422


def test_risk_allocation_round_trips(client, trader_headers):
    """The autonomy controller's capital allocation (P7) persists on the bot."""
    alloc = {"capital_fraction": 0.6, "risk_per_trade": 0.006}
    payload = make_bot_payload()
    payload["risk_allocation"] = alloc
    created = client.post("/bots", json=payload, headers=trader_headers)
    assert created.status_code == 201
    bot_id = created.json()["id"]
    assert created.json()["risk_allocation"] == alloc

    fetched = client.get(f"/bots/{bot_id}").json()
    assert fetched["risk_allocation"] == alloc

    # A bot created without it defaults to null.
    plain = create_bot(client, trader_headers, account_id="acct-noalloc")
    assert plain["risk_allocation"] is None


# --- read -----------------------------------------------------------------------


def test_list_and_get(client, trader_headers):
    bot = create_bot(client, trader_headers)
    create_bot(client, trader_headers, account_id="acct-2")

    all_bots = client.get("/bots").json()
    assert len(all_bots) == 2

    filtered = client.get("/bots", params={"account_id": "acct-2"}).json()
    assert len(filtered) == 1

    got = client.get(f"/bots/{bot['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == bot["id"]

    assert client.get("/bots/nope").status_code == 404


# --- update ---------------------------------------------------------------------


def test_patch_while_stopped(client, trader_headers):
    bot = create_bot(client, trader_headers)
    response = client.patch(
        f"/bots/{bot['id']}",
        json={"name": "renamed", "cycle_interval_seconds": 5},
        headers=trader_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "renamed"
    assert body["cycle_interval_seconds"] == 5


def test_patch_running_bot_conflicts(client, trader_headers, fake_clients):
    from app.clients import get_clients
    from app.main import app
    from app.orchestrator import runner

    app.dependency_overrides[get_clients] = lambda: fake_clients
    runner.clients_factory = lambda: fake_clients
    try:
        bot = create_bot(client, trader_headers)
        assert (
            client.post(f"/bots/{bot['id']}/start", headers=trader_headers).status_code
            == 200
        )
        response = client.patch(
            f"/bots/{bot['id']}", json={"name": "x"}, headers=trader_headers
        )
        assert response.status_code == 409
        client.post(f"/bots/{bot['id']}/stop", headers=trader_headers)
    finally:
        from app.clients import get_clients as real_factory

        runner.clients_factory = real_factory


def test_patch_to_live_requires_admin(client, trader_headers, admin_headers):
    bot = create_bot(client, trader_headers)
    response = client.patch(
        f"/bots/{bot['id']}", json={"execution_mode": "live"}, headers=trader_headers
    )
    assert response.status_code == 403

    response = client.patch(
        f"/bots/{bot['id']}", json={"execution_mode": "live"}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["execution_mode"] == "live"

    # ...and now a plain trader cannot edit the live bot at all
    response = client.patch(
        f"/bots/{bot['id']}", json={"name": "x"}, headers=trader_headers
    )
    assert response.status_code == 403


# --- start/stop -------------------------------------------------------------------


def test_start_stop_paper_bot(client, trader_headers, fake_clients):
    from app.clients import get_clients
    from app.orchestrator import runner

    runner.clients_factory = lambda: fake_clients
    try:
        bot = create_bot(client, trader_headers)
        started = client.post(f"/bots/{bot['id']}/start", headers=trader_headers)
        assert started.status_code == 200
        assert started.json()["bot"]["status"] == "running"

        # double start conflicts
        assert (
            client.post(f"/bots/{bot['id']}/start", headers=trader_headers).status_code
            == 409
        )

        stopped = client.post(f"/bots/{bot['id']}/stop", headers=trader_headers)
        assert stopped.status_code == 200
        assert stopped.json()["bot"]["status"] == "stopped"

        # double stop conflicts
        assert (
            client.post(f"/bots/{bot['id']}/stop", headers=trader_headers).status_code
            == 409
        )
    finally:
        runner.clients_factory = get_clients


def test_start_requires_auth_and_live_requires_admin(
    client, trader_headers, admin_headers, fake_clients
):
    from app.clients import get_clients
    from app.orchestrator import runner

    runner.clients_factory = lambda: fake_clients
    try:
        bot = create_bot(client, admin_headers, mode="live")
        assert client.post(f"/bots/{bot['id']}/start").status_code == 401
        assert (
            client.post(f"/bots/{bot['id']}/start", headers=trader_headers).status_code
            == 403
        )
        assert (
            client.post(f"/bots/{bot['id']}/start", headers=admin_headers).status_code
            == 200
        )
        assert (
            client.post(f"/bots/{bot['id']}/stop", headers=trader_headers).status_code
            == 403
        )
        assert (
            client.post(f"/bots/{bot['id']}/stop", headers=admin_headers).status_code
            == 200
        )
    finally:
        runner.clients_factory = get_clients


# --- cycles listing -----------------------------------------------------------------


def test_cycles_empty_and_404(client, trader_headers):
    bot = create_bot(client, trader_headers)
    response = client.get(f"/bots/{bot['id']}/cycles")
    assert response.status_code == 200
    assert response.json() == []
    assert client.get("/bots/nope/cycles").status_code == 404
