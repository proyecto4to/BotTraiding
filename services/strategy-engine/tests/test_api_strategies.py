"""GET/PATCH /strategies: listing, filtering, detail and enable/disable."""

from __future__ import annotations

from fastapi.testclient import TestClient

from trading_strategies import load_builtin_strategies, registry

from app import db as db_module
from app.main import app
from app.models import StrategyRecord, StrategyVersionRecord

load_builtin_strategies()


def test_startup_sync_populates_db(client: TestClient) -> None:
    with db_module.SessionLocal() as session:
        assert session.query(StrategyRecord).count() == len(registry)
        assert session.query(StrategyVersionRecord).count() == len(registry)
        row = (
            session.query(StrategyRecord)
            .filter_by(strategy_key="sma_crossover")
            .one()
        )
        assert row.enabled is True
        assert row.category == "trend"
        assert "crypto" in row.markets


def test_list_strategies(client: TestClient) -> None:
    response = client.get("/strategies")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(registry)
    keys = {item["key"] for item in body}
    assert "sma_crossover" in keys and "keltner_squeeze" in keys
    assert all(item["enabled"] is True for item in body)


def test_list_filter_by_category(client: TestClient) -> None:
    response = client.get("/strategies", params={"category": "trend"})
    assert response.status_code == 200
    assert {item["key"] for item in response.json()} == {
        "sma_crossover",
        "ema_crossover",
        "macd_trend",
    }


def test_list_filter_by_market_and_timeframe(client: TestClient) -> None:
    response = client.get("/strategies", params={"timeframe": "1m"})
    assert {item["key"] for item in response.json()} == {
        "opening_range_breakout",
        "vwap_reversion",
    }
    response = client.get(
        "/strategies", params={"market": "forex", "category": "mean_reversion"}
    )
    keys = {item["key"] for item in response.json()}
    assert "vwap_reversion" not in keys
    assert "bollinger_reversion" in keys


def test_list_invalid_category_rejected(client: TestClient) -> None:
    assert client.get("/strategies", params={"category": "astrology"}).status_code == 422


def test_get_strategy_detail(client: TestClient) -> None:
    response = client.get("/strategies/sma_crossover")
    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "sma_crossover"
    assert body["category"] == "trend"
    assert body["enabled"] is True
    assert body["db_id"]
    assert body["recommended_risk_per_trade"] > 0
    param_names = {p["name"] for p in body["parameters"]}
    assert {"fast_period", "slow_period", "atr_period"} <= param_names
    fast = next(p for p in body["parameters"] if p["name"] == "fast_period")
    assert fast["type"] == "int" and fast["default"] == 10
    assert fast["min"] == 2 and fast["max"] == 200


def test_get_unknown_strategy_404(client: TestClient) -> None:
    assert client.get("/strategies/does_not_exist").status_code == 404


def test_toggle_enable_disable(client: TestClient) -> None:
    response = client.patch("/strategies/sma_crossover", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    assert client.get("/strategies/sma_crossover").json()["enabled"] is False

    disabled = client.get("/strategies", params={"enabled": "false"}).json()
    assert {item["key"] for item in disabled} == {"sma_crossover"}
    enabled_keys = {
        item["key"] for item in client.get("/strategies", params={"enabled": "true"}).json()
    }
    assert "sma_crossover" not in enabled_keys

    response = client.patch("/strategies/sma_crossover", json={"enabled": True})
    assert response.json()["enabled"] is True


def test_toggle_unknown_strategy_404(client: TestClient) -> None:
    assert (
        client.patch("/strategies/nope", json={"enabled": False}).status_code == 404
    )


def test_disabled_state_survives_restart_sync() -> None:
    """DB owns enable/disable: a new startup sync must not re-enable."""
    with TestClient(app) as first:
        response = first.patch("/strategies/macd_trend", json={"enabled": False})
        assert response.status_code == 200
    with TestClient(app) as second:  # lifespan sync runs again
        assert second.get("/strategies/macd_trend").json()["enabled"] is False
        # metadata still synced from code registry
        assert second.get("/strategies/macd_trend").json()["version"]
