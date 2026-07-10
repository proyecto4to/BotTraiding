"""Simulated account lifecycle: create, read, reset, auto-create on order."""

from __future__ import annotations

import pytest

from tests.conftest import make_order_payload


def test_create_and_get_account(client):
    created = client.post(
        "/paper/accounts", json={"account_id": "acct-x", "starting_cash": 5_000.0}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["account_id"] == "acct-x"
    assert body["cash"] == 5_000.0
    assert body["starting_cash"] == 5_000.0
    assert body["equity"] == 5_000.0

    fetched = client.get("/paper/accounts/acct-x")
    assert fetched.status_code == 200
    assert fetched.json()["cash"] == 5_000.0


def test_create_account_generates_id_when_omitted(client):
    response = client.post("/paper/accounts", json={"starting_cash": 1_000.0})
    assert response.status_code == 201
    assert response.json()["account_id"]


def test_duplicate_account_conflict(client, account):
    response = client.post(
        "/paper/accounts", json={"account_id": "acct-1", "starting_cash": 1.0}
    )
    assert response.status_code == 409


def test_get_unknown_account_404(client):
    assert client.get("/paper/accounts/nope").status_code == 404
    assert client.get("/paper/positions/nope").status_code == 404


def test_reset_restores_cash_and_clears_positions(client, account, monkeypatch):
    monkeypatch.setenv("PAPER_SPREAD_BPS", "0")
    monkeypatch.setenv("PAPER_SLIPPAGE_BPS", "0")
    monkeypatch.setenv("PAPER_COMMISSION_BPS", "0")

    fill = client.post("/paper/orders", json=make_order_payload(quantity=10, price=100))
    assert fill.status_code == 200

    before = client.get("/paper/accounts/acct-1").json()
    assert before["cash"] == pytest.approx(99_000.0)
    assert len(client.get("/paper/positions/acct-1").json()) == 1

    reset = client.post("/paper/accounts/acct-1/reset")
    assert reset.status_code == 200
    assert reset.json()["cash"] == 100_000.0
    assert client.get("/paper/positions/acct-1").json() == []


def test_order_auto_creates_account_with_default_cash(client, monkeypatch):
    monkeypatch.setenv("PAPER_DEFAULT_STARTING_CASH", "50000")
    monkeypatch.setenv("PAPER_SPREAD_BPS", "0")
    monkeypatch.setenv("PAPER_SLIPPAGE_BPS", "0")
    monkeypatch.setenv("PAPER_COMMISSION_BPS", "0")

    fill = client.post(
        "/paper/orders", json=make_order_payload(account_id="fresh", quantity=1, price=100)
    )
    assert fill.status_code == 200
    assert fill.json()["status"] == "filled"

    account = client.get("/paper/accounts/fresh").json()
    assert account["starting_cash"] == 50_000.0
    assert account["cash"] == pytest.approx(49_900.0)
