"""Exposure aggregation (symbol/sector/currency) and correlation matrix."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.portfolio import compute_correlation_matrix

ACC = "acc-exp"


def _fill(client, symbol, side, qty, price, sector=None, currency="USD"):
    return client.post(
        f"/portfolio/{ACC}/executions",
        json={
            "order_id": str(uuid.uuid4()),
            "status": "filled",
            "filled_quantity": qty,
            "average_fill_price": price,
            "broker": "sim",
            "reported_at": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "sector": sector,
            "currency": currency,
        },
    )


def test_exposure_per_symbol_sector_currency(client):
    _fill(client, "AAPL", "buy", 100, 100, sector="tech")
    _fill(client, "MSFT", "buy", 50, 200, sector="tech")
    _fill(client, "XOM", "sell", 100, 50, sector="energy", currency="EUR")

    exp = client.get(f"/portfolio/{ACC}/exposure").json()
    assert exp["per_symbol"]["AAPL"] == pytest.approx(10000.0)
    assert exp["per_symbol"]["MSFT"] == pytest.approx(10000.0)
    assert exp["per_symbol"]["XOM"] == pytest.approx(5000.0)
    assert exp["per_sector"]["tech"] == pytest.approx(20000.0)
    assert exp["per_sector"]["energy"] == pytest.approx(5000.0)
    assert exp["per_currency"]["USD"] == pytest.approx(20000.0)
    assert exp["per_currency"]["EUR"] == pytest.approx(5000.0)
    assert exp["gross_exposure"] == pytest.approx(25000.0)
    assert exp["net_exposure"] == pytest.approx(15000.0)  # short XOM subtracts
    assert exp["leverage"] == pytest.approx(25000.0 / 100000.0)


def test_correlation_matrix_of_open_positions(client):
    _fill(client, "AAPL", "buy", 10, 100)
    _fill(client, "MSFT", "buy", 10, 200)

    returns = {
        "AAPL": [0.01, -0.02, 0.03, 0.01, -0.01],
        "MSFT": [-0.01, 0.02, -0.03, -0.01, 0.01],  # exact inverse
        "GHOST": [0.5, 0.5, 0.5],  # not an open position -> excluded
    }
    client.post(f"/portfolio/{ACC}/mark", json={"prices": {}, "returns": returns})

    exp = client.get(f"/portfolio/{ACC}/exposure").json()
    matrix = exp["correlation_matrix"]
    assert set(matrix.keys()) == {"AAPL", "MSFT"}
    assert matrix["AAPL"]["AAPL"] == pytest.approx(1.0)
    assert matrix["AAPL"]["MSFT"] == pytest.approx(-1.0)
    assert matrix["MSFT"]["AAPL"] == pytest.approx(-1.0)


def test_compute_correlation_matrix_known_values():
    returns = {
        "A": [0.01, 0.02, 0.03, 0.04],
        "B": [0.02, 0.04, 0.06, 0.08],  # perfectly correlated with A
        "C": [0.04, 0.03, 0.02, 0.01],  # perfectly anti-correlated
    }
    matrix = compute_correlation_matrix(returns, ["A", "B", "C"])
    assert matrix["A"]["B"] == pytest.approx(1.0)
    assert matrix["A"]["C"] == pytest.approx(-1.0)
    assert matrix["B"]["C"] == pytest.approx(-1.0)


def test_correlation_handles_short_or_flat_series():
    returns = {"A": [0.01], "B": [0.0, 0.0, 0.0], "C": [0.01, 0.02, 0.03]}
    matrix = compute_correlation_matrix(returns, ["A", "B", "C"])
    assert "A" not in matrix  # too short
    assert matrix["B"]["C"] == 0.0  # zero-variance series -> 0, not NaN


def test_returns_series_served_in_snapshot(client):
    _fill(client, "AAPL", "buy", 10, 100)
    client.post(
        f"/portfolio/{ACC}/mark",
        json={"prices": {"AAPL": 101}, "returns": {"AAPL": [0.01, 0.02]}},
    )
    state = client.get(f"/portfolio/{ACC}").json()
    assert state["returns"]["AAPL"] == [0.01, 0.02]
    assert state["marks"]["AAPL"] == 101
