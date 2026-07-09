"""POST /strategies/{id}/evaluate: the seam trading-engine/backtester call."""

from __future__ import annotations

from fastapi.testclient import TestClient

from trading_contracts import TradeSignal
from trading_strategies import load_builtin_strategies, registry

from app import events

from .synthetic import first_signal_prefix, flat_bars, trend_up_bars

load_builtin_strategies()

USER = "11111111-1111-1111-1111-111111111111"


class CapturePublisher(events.SignalPublisher):
    def __init__(self) -> None:
        self.published: list[TradeSignal] = []

    async def publish_signal(self, signal: TradeSignal) -> None:
        self.published.append(signal)


def _bars_json(bars) -> list[dict]:
    return [bar.model_dump(mode="json") for bar in bars]


def _trigger_bars():
    prefix = first_signal_prefix(registry.create("sma_crossover"), trend_up_bars())
    assert prefix is not None
    return prefix


def test_evaluate_returns_signal_and_publishes(client: TestClient) -> None:
    publisher = CapturePublisher()
    events.set_publisher(publisher)
    response = client.post(
        "/strategies/sma_crossover/evaluate",
        json={"bars": _bars_json(_trigger_bars()), "market": "crypto"},
    )
    assert response.status_code == 200
    body = response.json()
    signal = body["signal"]
    assert signal is not None
    assert signal["strategy_id"] == "sma_crossover"
    assert signal["side"] == "buy"
    assert signal["market"] == "crypto"
    assert signal["stop_loss"] is not None and signal["take_profit"] is not None
    assert body["params_used"]["fast_period"] == 10
    assert len(publisher.published) == 1
    assert publisher.published[0].strategy_id == "sma_crossover"


def test_evaluate_returns_null_when_no_setup(client: TestClient) -> None:
    publisher = CapturePublisher()
    events.set_publisher(publisher)
    response = client.post(
        "/strategies/sma_crossover/evaluate",
        json={"bars": _bars_json(flat_bars(60))},
    )
    assert response.status_code == 200
    assert response.json()["signal"] is None
    assert publisher.published == []


def test_evaluate_applies_stored_user_config(client: TestClient) -> None:
    client.put(
        "/strategies/sma_crossover/config",
        json={"user_id": USER, "overrides": {"fast_period": 5}},
    )
    response = client.post(
        "/strategies/sma_crossover/evaluate",
        json={"bars": _bars_json(flat_bars(60)), "user_id": USER},
    )
    assert response.status_code == 200
    assert response.json()["params_used"]["fast_period"] == 5


def test_evaluate_body_params_win_over_stored_config(client: TestClient) -> None:
    client.put(
        "/strategies/sma_crossover/config",
        json={"user_id": USER, "overrides": {"fast_period": 5}},
    )
    response = client.post(
        "/strategies/sma_crossover/evaluate",
        json={
            "bars": _bars_json(flat_bars(60)),
            "user_id": USER,
            "params": {"fast_period": 7},
        },
    )
    assert response.json()["params_used"]["fast_period"] == 7


def test_evaluate_rejects_invalid_params(client: TestClient) -> None:
    response = client.post(
        "/strategies/sma_crossover/evaluate",
        json={"bars": _bars_json(flat_bars(60)), "params": {"fast_period": 0}},
    )
    assert response.status_code == 422


def test_evaluate_disabled_strategy_conflict_unless_forced(client: TestClient) -> None:
    client.patch("/strategies/sma_crossover", json={"enabled": False})
    payload = {"bars": _bars_json(flat_bars(60))}
    assert (
        client.post("/strategies/sma_crossover/evaluate", json=payload).status_code
        == 409
    )
    forced = client.post(
        "/strategies/sma_crossover/evaluate", params={"force": "true"}, json=payload
    )
    assert forced.status_code == 200


def test_evaluate_unknown_strategy_404(client: TestClient) -> None:
    response = client.post(
        "/strategies/nope/evaluate", json={"bars": _bars_json(flat_bars(10))}
    )
    assert response.status_code == 404


def test_evaluate_requires_bars(client: TestClient) -> None:
    assert (
        client.post("/strategies/sma_crossover/evaluate", json={"bars": []}).status_code
        == 422
    )
