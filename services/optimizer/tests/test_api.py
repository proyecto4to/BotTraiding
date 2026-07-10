"""Optimizer API round-trip with mocked BacktesterClient/StrategyEngineClient."""

from __future__ import annotations

from typing import Any

from app import clients, events
from app.events import EventPublisher

from tests.fakes import (
    BASELINE_FAST,
    FakeBacktesterClient,
    FakeStrategyEngineClient,
    baseline_beats_candidates,
    candidates_beat_baseline,
)


class CapturingPublisher(EventPublisher):
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, subject: str, payload: dict[str, Any]) -> None:
        self.published.append((subject, payload))


def _request(promote: bool = False, budget: int = 6) -> dict:
    return {
        "strategy_key": "sma_crossover",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "start": "2025-01-01T00:00:00",
        "end": "2026-01-01T00:00:00",
        "search_type": "grid",
        "budget": budget,
        "n_windows": 2,
        "is_fraction": 0.75,
        "current_params": {"fast_period": BASELINE_FAST, "slow_period": 50},
        "promote": promote,
    }


def test_round_trip_better_candidates_recommend_promotion(client) -> None:
    fake_bt = FakeBacktesterClient(candidates_beat_baseline)
    clients.set_backtester(fake_bt)
    capture = CapturingPublisher()
    events.set_publisher(capture)

    resp = client.post("/optimize", json=_request())
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "completed"
    assert body["promoted"] is True  # gate passed -> promotion recommended
    assert body["applied"] is False  # but promote=false -> nothing applied
    assert body["decision"]["promote"] is True
    assert body["best_params"]["fast_period"] != BASELINE_FAST
    assert fake_bt.calls, "the mocked backtester must have been used"

    # recommendation event, and ONLY the recommendation event
    subjects = [s for s, _ in capture.published]
    assert subjects == [events.PROMOTION_RECOMMENDED_SUBJECT]

    # GET /optimize/{id}: full results with IS/OOS + candidate/baseline
    detail = client.get(f"/optimize/{body['id']}").json()
    assert detail["status"] == "completed"
    results = detail["results"]
    assert any(r["out_of_sample"] for r in results)
    assert any(not r["out_of_sample"] for r in results)
    assert {r["role"] for r in results} == {"candidate", "baseline"}
    assert all(r["window_index"] in (0, 1) for r in results)

    # GET /optimize?strategy_key=
    listing = client.get("/optimize", params={"strategy_key": "sma_crossover"}).json()
    assert [r["id"] for r in listing] == [body["id"]]
    assert client.get("/optimize", params={"strategy_key": "other"}).json() == []


def test_worse_oos_rejects_and_never_applies(client) -> None:
    fake_bt = FakeBacktesterClient(baseline_beats_candidates)
    fake_se = FakeStrategyEngineClient()
    clients.set_backtester(fake_bt)
    clients.set_strategy_engine(fake_se)
    capture = CapturingPublisher()
    events.set_publisher(capture)

    resp = client.post("/optimize", json=_request(promote=True))
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "completed"
    assert body["promoted"] is False
    assert body["applied"] is False
    assert body["decision"]["promote"] is False
    assert any("<" in r for r in body["decision"]["reasons"])
    # even with promote=true, a failed gate NEVER touches strategy-engine
    assert fake_se.applied == []
    assert capture.published == []


def test_promote_true_applies_via_strategy_engine(client) -> None:
    fake_bt = FakeBacktesterClient(candidates_beat_baseline)
    fake_se = FakeStrategyEngineClient()
    clients.set_backtester(fake_bt)
    clients.set_strategy_engine(fake_se)
    capture = CapturingPublisher()
    events.set_publisher(capture)

    resp = client.post("/optimize", json=_request(promote=True))
    body = resp.json()
    assert body["promoted"] is True
    assert body["applied"] is True
    assert len(fake_se.applied) == 1
    key, params = fake_se.applied[0]
    assert key == "sma_crossover"
    assert params == body["best_params"]
    subjects = [s for s, _ in capture.published]
    assert subjects == [
        events.PROMOTION_RECOMMENDED_SUBJECT,
        events.PARAMS_APPLIED_SUBJECT,
    ]


def test_equal_oos_respects_threshold_env(client, monkeypatch) -> None:
    # identical metrics for everything -> equal OOS -> threshold decides
    fake_bt = FakeBacktesterClient(lambda params: 1.0)
    clients.set_backtester(fake_bt)

    resp = client.post("/optimize", json=_request())
    assert resp.json()["promoted"] is False  # default threshold 1.05

    monkeypatch.setenv("PROMOTION_THRESHOLD", "1.0")
    resp = client.post("/optimize", json=_request())
    assert resp.json()["promoted"] is True


def test_large_budget_runs_in_background(client, monkeypatch) -> None:
    monkeypatch.setenv("OPTIMIZER_SYNC_BUDGET", "2")
    fake_bt = FakeBacktesterClient(candidates_beat_baseline)
    clients.set_backtester(fake_bt)

    resp = client.post("/optimize", json=_request(budget=6))
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"  # scheduled, not executed inline
    # TestClient runs background tasks on response completion
    detail = client.get(f"/optimize/{resp.json()['id']}").json()
    assert detail["status"] == "completed"


def test_unknown_strategy_404_and_bad_params_422(client) -> None:
    clients.set_backtester(FakeBacktesterClient(lambda p: 1.0))
    bad = _request()
    bad["strategy_key"] = "does_not_exist"
    assert client.post("/optimize", json=bad).status_code == 404

    bad = _request()
    bad["current_params"] = {"fast_period": -5}
    assert client.post("/optimize", json=bad).status_code == 422

    assert client.get("/optimize/nope").status_code == 404
