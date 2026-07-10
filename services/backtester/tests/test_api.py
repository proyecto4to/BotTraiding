"""Full API round-trip tests via TestClient (in-memory SQLite persistence)."""

from __future__ import annotations


def _synthetic_request(**overrides) -> dict:
    body = {
        "strategy_key": "sma_crossover",
        "params": {"fast_period": 10, "slow_period": 30},
        "symbol": "SYNUSD",
        "timeframe": "1h",
        "initial_capital": 100_000.0,
        "friction": {"spread_bps": 2.0, "slippage_bps": 1.0, "commission_bps": 1.0},
        "data": {
            "source": "synthetic",
            "regime": "trend",
            "n_bars": 500,
            "seed": 7,
            "drift": 0.004,
            "volatility": 0.008,
        },
    }
    body.update(overrides)
    return body


CSV = "timestamp,open,high,low,close,volume\n" + "".join(
    f"2024-01-01T{h:02d}:00:00Z,{100+h},{101+h},{99+h},{100.5+h},1000\n"
    for h in range(24)
)


def test_post_backtest_returns_persisted_results(client) -> None:
    response = client.post("/backtests", json=_synthetic_request())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["strategy_key"] == "sma_crossover"
    assert body["parameters"]["fast_period"] == 10  # defaults merged in too
    assert body["metrics"]["trade_count"] >= 1
    assert body["metrics"]["total_return"] > 0.0
    assert len(body["equity_curve"]) == 500
    assert body["trades"]
    assert body["error"] is None

    # GET /backtests/{id} round-trips the same persisted results
    detail = client.get(f"/backtests/{body['id']}")
    assert detail.status_code == 200
    fetched = detail.json()
    assert fetched["metrics"] == body["metrics"]
    assert fetched["equity_curve"] == body["equity_curve"]
    assert fetched["trades"] == body["trades"]
    assert fetched["status"] == "completed"


def test_list_and_filter_backtests(client) -> None:
    run1 = client.post("/backtests", json=_synthetic_request()).json()
    run2 = client.post(
        "/backtests",
        json=_synthetic_request(strategy_key="ema_crossover", params={}),
    ).json()

    everything = client.get("/backtests").json()
    assert {r["id"] for r in everything} >= {run1["id"], run2["id"]}
    assert all("equity_curve" not in r for r in everything)  # summaries only

    only_sma = client.get("/backtests", params={"strategy_key": "sma_crossover"}).json()
    assert {r["strategy_key"] for r in only_sma} == {"sma_crossover"}
    assert any(r["id"] == run1["id"] for r in only_sma)
    assert all(r["metrics"] is not None for r in only_sma)  # comparable metrics

    none = client.get("/backtests", params={"strategy_key": "no_such"}).json()
    assert none == []


def test_post_csv_content_backtest(client) -> None:
    request = _synthetic_request(
        data={"source": "csv", "content": CSV},
        params={"fast_period": 3, "slow_period": 5},
    )
    response = client.post("/backtests", json=request)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["equity_curve"]) == 24


def test_post_unknown_strategy_is_404(client) -> None:
    response = client.post("/backtests", json=_synthetic_request(strategy_key="nope"))
    assert response.status_code == 404
    assert "unknown strategy_key" in response.json()["detail"]


def test_post_invalid_params_is_400(client) -> None:
    response = client.post(
        "/backtests",
        json=_synthetic_request(params={"fast_period": 50, "slow_period": 10}),
    )
    assert response.status_code == 400
    assert "fast_period" in response.json()["detail"]


def test_post_bad_csv_is_400(client) -> None:
    response = client.post(
        "/backtests", json=_synthetic_request(data={"source": "csv", "content": "a,b\n1,2\n"})
    )
    assert response.status_code == 400


def test_post_too_many_bars_is_400(client) -> None:
    request = _synthetic_request()
    request["data"]["n_bars"] = 50_000  # > BACKTESTER_MAX_BARS default 20000
    response = client.post("/backtests", json=request)
    assert response.status_code == 400
    assert "BACKTESTER_MAX_BARS" in response.json()["detail"]


def test_post_empty_range_is_400(client) -> None:
    request = _synthetic_request(start="2030-01-01T00:00:00Z")
    response = client.post("/backtests", json=request)
    assert response.status_code == 400
    assert "no bars" in response.json()["detail"]


def test_get_unknown_run_is_404(client) -> None:
    response = client.get("/backtests/does-not-exist")
    assert response.status_code == 404


def test_data_config_requires_exactly_one_csv_input(client) -> None:
    request = _synthetic_request(data={"source": "csv"})
    response = client.post("/backtests", json=request)
    assert response.status_code == 422  # pydantic validation
