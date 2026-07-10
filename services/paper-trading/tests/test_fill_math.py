"""Exact fill-model math: spread, slippage, size impact and commission.

Configuration used in the buy/sell tests:
    spread 20 bps (10 bps per side), slippage 10 bps,
    size impact 0.5 bps per unit (x10 units = 5 bps),
    commission 10 bps + 0.1 per unit.

Buy 10 @ mid 100:
    adjustment = 10 + 10 + 5 = 25 bps -> fill 100 * 1.0025 = 100.25
    notional   = 1002.5
    commission = 1002.5 * 0.001 + 0.1 * 10 = 2.0025
    cash       = 100000 - 1002.5 - 2.0025 = 98995.4975
Sell 10 @ mid 100 afterwards:
    fill 100 * 0.9975 = 99.75, notional 997.5, commission 1.9975
    cash = 98995.4975 + 997.5 - 1.9975 = 99991.0
"""

from __future__ import annotations

import pytest

from tests.conftest import make_order_payload

APPROX = dict(rel=1e-12)


@pytest.fixture()
def fill_env(monkeypatch):
    monkeypatch.setenv("PAPER_SPREAD_BPS", "20")
    monkeypatch.setenv("PAPER_SLIPPAGE_BPS", "10")
    monkeypatch.setenv("PAPER_SIZE_IMPACT_BPS_PER_UNIT", "0.5")
    monkeypatch.setenv("PAPER_COMMISSION_BPS", "10")
    monkeypatch.setenv("PAPER_COMMISSION_PER_UNIT", "0.1")


def test_buy_fill_math_exact(client, account, fill_env):
    response = client.post("/paper/orders", json=make_order_payload(quantity=10, price=100))
    assert response.status_code == 200, response.text
    report = response.json()

    assert report["status"] == "filled"
    assert report["filled_quantity"] == 10.0
    assert report["average_fill_price"] == pytest.approx(100.25, **APPROX)
    assert report["broker"] == "paper"
    assert report["raw"]["total_adjustment_bps"] == pytest.approx(25.0, **APPROX)
    assert report["raw"]["size_impact_bps"] == pytest.approx(5.0, **APPROX)
    assert report["raw"]["commission"] == pytest.approx(2.0025, **APPROX)

    account_state = client.get("/paper/accounts/acct-1").json()
    assert account_state["cash"] == pytest.approx(98_995.4975, **APPROX)

    positions = client.get("/paper/positions/acct-1").json()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 10.0
    assert positions[0]["average_price"] == pytest.approx(100.25, **APPROX)


def test_sell_fill_math_exact_and_flat_position(client, account, fill_env):
    buy = client.post("/paper/orders", json=make_order_payload(quantity=10, price=100))
    assert buy.status_code == 200

    sell = client.post(
        "/paper/orders", json=make_order_payload(side="sell", quantity=10, price=100)
    )
    assert sell.status_code == 200
    report = sell.json()

    assert report["status"] == "filled"
    assert report["average_fill_price"] == pytest.approx(99.75, **APPROX)
    assert report["raw"]["commission"] == pytest.approx(1.9975, **APPROX)

    account_state = client.get("/paper/accounts/acct-1").json()
    assert account_state["cash"] == pytest.approx(99_991.0, **APPROX)
    # Round trip cost = 9.0 = full spread (2.0) + 2x slippage+impact (3.0)? No:
    # cost = 2 * (25 bps of ~1000 notional) + commissions = 5.0 + 4.0 = 9.0.
    assert client.get("/paper/positions/acct-1").json() == []


def test_zero_adjustment_fills_at_mid(client, account, monkeypatch):
    monkeypatch.setenv("PAPER_SPREAD_BPS", "0")
    monkeypatch.setenv("PAPER_SLIPPAGE_BPS", "0")
    monkeypatch.setenv("PAPER_COMMISSION_BPS", "0")

    response = client.post("/paper/orders", json=make_order_payload(quantity=5, price=123.45))
    report = response.json()
    assert report["average_fill_price"] == pytest.approx(123.45, **APPROX)
    assert report["raw"]["commission"] == 0.0

    account_state = client.get("/paper/accounts/acct-1").json()
    assert account_state["cash"] == pytest.approx(100_000.0 - 5 * 123.45, **APPROX)


def test_per_unit_commission_only(client, account, monkeypatch):
    monkeypatch.setenv("PAPER_SPREAD_BPS", "0")
    monkeypatch.setenv("PAPER_SLIPPAGE_BPS", "0")
    monkeypatch.setenv("PAPER_COMMISSION_BPS", "0")
    monkeypatch.setenv("PAPER_COMMISSION_PER_UNIT", "0.25")

    response = client.post("/paper/orders", json=make_order_payload(quantity=8, price=50))
    assert response.json()["raw"]["commission"] == pytest.approx(2.0, **APPROX)

    account_state = client.get("/paper/accounts/acct-1").json()
    assert account_state["cash"] == pytest.approx(100_000.0 - 400.0 - 2.0, **APPROX)


def test_buy_averages_position_price(client, account, monkeypatch):
    monkeypatch.setenv("PAPER_SPREAD_BPS", "0")
    monkeypatch.setenv("PAPER_SLIPPAGE_BPS", "0")
    monkeypatch.setenv("PAPER_COMMISSION_BPS", "0")

    client.post("/paper/orders", json=make_order_payload(quantity=10, price=100))
    client.post("/paper/orders", json=make_order_payload(quantity=10, price=110))

    positions = client.get("/paper/positions/acct-1").json()
    assert positions[0]["quantity"] == 20.0
    assert positions[0]["average_price"] == pytest.approx(105.0, **APPROX)


def test_duplicate_order_id_conflict(client, account):
    payload = make_order_payload(quantity=1, price=100)
    assert client.post("/paper/orders", json=payload).status_code == 200
    assert client.post("/paper/orders", json=payload).status_code == 409
