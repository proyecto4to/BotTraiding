"""Latency simulation config and order cancel flow."""

from __future__ import annotations

import pytest

from app import engine
from tests.conftest import make_order_payload


@pytest.fixture()
def flat_env(monkeypatch):
    monkeypatch.setenv("PAPER_SPREAD_BPS", "0")
    monkeypatch.setenv("PAPER_SLIPPAGE_BPS", "0")
    monkeypatch.setenv("PAPER_COMMISSION_BPS", "0")


def test_latency_config_delays_fill(client, account, flat_env, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(engine, "_sleep", fake_sleep)
    monkeypatch.setenv("PAPER_LATENCY_MS", "250")

    response = client.post("/paper/orders", json=make_order_payload(quantity=1, price=100))
    assert response.status_code == 200
    assert sleeps == [0.25]
    assert response.json()["raw"]["latency_ms"] == 250.0


def test_no_latency_by_default(client, account, flat_env, monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(engine, "_sleep", fake_sleep)

    client.post("/paper/orders", json=make_order_payload(quantity=1, price=100))
    assert sleeps == []


def test_cancel_partially_filled_order(client, account, flat_env, monkeypatch):
    monkeypatch.setenv("PAPER_MAX_FILL_QUANTITY", "60")

    payload = make_order_payload(quantity=100, price=100)
    placed = client.post("/paper/orders", json=payload)
    assert placed.json()["status"] == "partially_filled"

    cancelled = client.post(f"/paper/orders/{payload['order_id']}/cancel")
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert body["filled_quantity"] == 60.0  # the filled part stays filled

    fetched = client.get(f"/paper/orders/{payload['order_id']}")
    assert fetched.json()["status"] == "cancelled"


def test_cancel_filled_order_conflict(client, account, flat_env):
    payload = make_order_payload(quantity=1, price=100)
    assert client.post("/paper/orders", json=payload).json()["status"] == "filled"

    response = client.post(f"/paper/orders/{payload['order_id']}/cancel")
    assert response.status_code == 409


def test_cancel_and_get_unknown_order_404(client):
    assert client.get("/paper/orders/does-not-exist").status_code == 404
    assert client.post("/paper/orders/does-not-exist/cancel").status_code == 404
