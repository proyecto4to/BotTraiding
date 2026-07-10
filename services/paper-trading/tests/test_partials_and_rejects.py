"""Partial fills, reject scenarios and short-selling config."""

from __future__ import annotations

import pytest

from tests.conftest import make_order_payload


@pytest.fixture()
def flat_env(monkeypatch):
    monkeypatch.setenv("PAPER_SPREAD_BPS", "0")
    monkeypatch.setenv("PAPER_SLIPPAGE_BPS", "0")
    monkeypatch.setenv("PAPER_COMMISSION_BPS", "0")


def test_partial_fill_above_max_fill_quantity(client, account, flat_env, monkeypatch):
    monkeypatch.setenv("PAPER_MAX_FILL_QUANTITY", "60")

    response = client.post("/paper/orders", json=make_order_payload(quantity=100, price=100))
    report = response.json()

    assert report["status"] == "partially_filled"
    assert report["filled_quantity"] == 60.0
    assert report["average_fill_price"] == pytest.approx(100.0)
    assert report["raw"]["requested_quantity"] == 100.0

    account_state = client.get("/paper/accounts/acct-1").json()
    assert account_state["cash"] == pytest.approx(100_000.0 - 6_000.0)

    positions = client.get("/paper/positions/acct-1").json()
    assert positions[0]["quantity"] == 60.0


def test_insufficient_balance_rejected(client, flat_env):
    created = client.post(
        "/paper/accounts", json={"account_id": "poor", "starting_cash": 1_000.0}
    )
    assert created.status_code == 201

    response = client.post(
        "/paper/orders", json=make_order_payload(account_id="poor", quantity=100, price=100)
    )
    report = response.json()

    assert report["status"] == "rejected"
    assert report["filled_quantity"] == 0.0
    assert report["average_fill_price"] is None
    assert report["raw"]["reason"] == "insufficient_balance"

    # No cash or position side effects.
    account_state = client.get("/paper/accounts/poor").json()
    assert account_state["cash"] == 1_000.0
    assert client.get("/paper/positions/poor").json() == []


def test_sell_without_position_rejected_when_shorting_disabled(
    client, account, flat_env, monkeypatch
):
    monkeypatch.setenv("PAPER_ALLOW_SHORT", "false")

    response = client.post(
        "/paper/orders", json=make_order_payload(side="sell", quantity=5, price=100)
    )
    report = response.json()
    assert report["status"] == "rejected"
    assert report["raw"]["reason"] == "insufficient_position"


def test_sell_without_position_opens_short_by_default(client, account, flat_env):
    response = client.post(
        "/paper/orders", json=make_order_payload(side="sell", quantity=5, price=100)
    )
    assert response.json()["status"] == "filled"

    positions = client.get("/paper/positions/acct-1").json()
    assert positions[0]["quantity"] == -5.0
    assert positions[0]["average_price"] == pytest.approx(100.0)

    account_state = client.get("/paper/accounts/acct-1").json()
    assert account_state["cash"] == pytest.approx(100_500.0)
