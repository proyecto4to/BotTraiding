"""API round-trips: regime, refresh (injected provider), select, anomalies,
underperformance -> persisted recommendations + published events."""

from __future__ import annotations

from typing import Any

from app import events, providers
from app.events import EventPublisher

from tests.synthetic import make_bars, trending_closes, vol_shift_closes


class CapturingPublisher(EventPublisher):
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        self.published.append((subject, payload))


class FakeBarProvider(providers.BarProvider):
    def __init__(self, closes: list[float]) -> None:
        self._closes = closes
        self.calls: list[tuple[str, str, int]] = []

    async def get_bars(self, symbol: str, timeframe: str, limit: int):
        self.calls.append((symbol, timeframe, limit))
        return make_bars(self._closes[:limit], symbol=symbol, timeframe=timeframe)


def _bars_payload(closes: list[float]) -> list[dict]:
    return [b.model_dump(mode="json") for b in make_bars(closes)]


def test_regime_endpoint_classifies_and_publishes(client) -> None:
    capture = CapturingPublisher()
    events.set_publisher(capture)

    resp = client.post("/ai/regime", json={"bars": _bars_payload(trending_closes())})
    assert resp.status_code == 200
    body = resp.json()
    assert body["trend"] == "up"
    assert body["volatility"] in ("low", "normal", "high")
    assert 0.0 <= body["confidence"] <= 1.0
    assert [s for s, _ in capture.published] == [events.REGIME_UPDATED_SUBJECT]


def test_regime_endpoint_rejects_short_series(client) -> None:
    resp = client.post("/ai/regime", json={"bars": _bars_payload(trending_closes(n=5))})
    assert resp.status_code == 422


def test_regime_refresh_without_provider_degrades(client) -> None:
    resp = client.post("/ai/regime/refresh", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["refreshed"] == []
    assert "no bar provider" in body["detail"]


def test_regime_refresh_with_injected_provider(client) -> None:
    provider = FakeBarProvider(vol_shift_closes())
    providers.set_bar_provider(provider)
    capture = CapturingPublisher()
    events.set_publisher(capture)

    resp = client.post(
        "/ai/regime/refresh",
        json={"symbols": ["BTC/USDT", "ETH/USDT"], "timeframe": "1h", "limit": 200},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert [r["symbol"] for r in body["refreshed"]] == ["BTC/USDT", "ETH/USDT"]
    assert all(r["regime"] is not None for r in body["refreshed"])
    assert len(provider.calls) == 2
    assert len(capture.published) == 2


def test_select_endpoint_with_explicit_strategies(client) -> None:
    payload = {
        "regime": {"trend": "sideways", "volatility": "normal", "confidence": 0.9},
        "strategies": [
            {"key": "trendy", "category": "trend"},
            {"key": "reverty", "category": "mean_reversion"},
        ],
        "performance": [
            {"strategy_key": "trendy", "sharpe": 1.0},
            {"strategy_key": "reverty", "sharpe": 1.0},
        ],
    }
    resp = client.post("/ai/select", json=payload)
    assert resp.status_code == 200
    ranked = resp.json()["ranked"]
    assert [s["key"] for s in ranked] == ["reverty", "trendy"]
    assert sum(s["weight"] for s in ranked) == 1.0


def test_select_endpoint_defaults_to_registry(client) -> None:
    payload = {
        "regime": {"trend": "up", "volatility": "normal", "confidence": 0.7},
        "performance": [],
    }
    resp = client.post("/ai/select", json=payload)
    assert resp.status_code == 200
    ranked = resp.json()["ranked"]
    assert len(ranked) >= 16  # the shared library
    assert abs(sum(s["weight"] for s in ranked) - 1.0) < 1e-9


def test_anomalies_endpoint(client) -> None:
    payload = {
        "series": [
            {"strategy_key": "s1", "kind": "returns", "values": [0.001] * 25 + [0.4]},
            {"strategy_key": "s2", "kind": "equity", "values": [100.0] * 15 + [60.0]},
        ]
    }
    resp = client.post("/ai/anomalies", json=payload)
    assert resp.status_code == 200
    flags = resp.json()["flags"]
    types = {f["anomaly_type"] for f in flags}
    assert types == {"return_zscore", "drawdown_velocity"}
    assert {f["strategy_key"] for f in flags} == {"s1", "s2"}


def test_underperformance_persists_and_publishes(client) -> None:
    capture = CapturingPublisher()
    events.set_publisher(capture)
    losing = [-0.01, 0.001, -0.02, 0.002, -0.015] * 8  # 40 trades, bad Sharpe

    resp = client.post(
        "/ai/underperformance",
        json={"records": [{"strategy_key": "bad_strategy", "trade_returns": losing}]},
    )
    assert resp.status_code == 200
    recs = resp.json()["recommendations"]
    assert recs and all(r["action"] == "disable" for r in recs)

    # published one event per recommendation, never an "apply" action
    subjects = [s for s, _ in capture.published]
    assert subjects == [events.RECOMMENDATION_CREATED_SUBJECT] * len(recs)

    # persisted: visible through GET /ai/recommendations
    listing = client.get("/ai/recommendations", params={"strategy_key": "bad_strategy"})
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == len(recs)
    assert rows[0]["strategy_key"] == "bad_strategy"
    assert rows[0]["id"]


def test_underperformance_persist_false_skips_storage(client) -> None:
    losing = [-0.02] * 40
    resp = client.post(
        "/ai/underperformance",
        json={
            "records": [{"strategy_key": "ephemeral", "trade_returns": losing}],
            "persist": False,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["recommendations"]
    assert client.get("/ai/recommendations").json() == []


def test_recommendations_filter_and_limit(client) -> None:
    losing = [-0.02] * 40
    for key in ("k1", "k2"):
        client.post(
            "/ai/underperformance",
            json={"records": [{"strategy_key": key, "trade_returns": losing}]},
        )
    all_rows = client.get("/ai/recommendations").json()
    assert {r["strategy_key"] for r in all_rows} == {"k1", "k2"}
    only_k1 = client.get("/ai/recommendations", params={"strategy_key": "k1"}).json()
    assert all(r["strategy_key"] == "k1" for r in only_k1)
    limited = client.get("/ai/recommendations", params={"limit": 1}).json()
    assert len(limited) == 1
