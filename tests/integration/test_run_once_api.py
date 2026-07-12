"""Full-stack round trip through trading-engine's OWN API: create a bot via
POST /bots (real JWT), drive one cycle via POST /bots/{id}/run-once, and
verify the CycleReport plus the downstream effects in the real
execution-engine / paper-trading / portfolio-engine apps.
"""

from __future__ import annotations

from .conftest import auth_headers, synthetic_uptrend_bars

ACCOUNT = "acct-int-api"
SYMBOL = "BTCUSD"


def _bot_payload() -> dict:
    return {
        "name": "api-bot",
        "account_id": ACCOUNT,
        "broker": "binance",
        "execution_mode": "paper",
        "symbols": [SYMBOL],
        "timeframe": "1h",
        "strategy_keys": ["sma_crossover"],
        "params_overrides": {},
        "cycle_interval_seconds": 60,
    }


def test_run_once_through_trading_engine_api(platform):
    from fastapi.testclient import TestClient

    platform.bars_by_symbol[SYMBOL] = synthetic_uptrend_bars(symbol=SYMBOL)
    headers = auth_headers(["trader"])

    with TestClient(platform.trading.app) as client:
        created = client.post("/bots", json=_bot_payload(), headers=headers)
        assert created.status_code == 201, created.text
        bot = created.json()
        assert bot["status"] == "stopped"

        response = client.post(f"/bots/{bot['id']}/run-once", headers=headers)
        assert response.status_code == 200, response.text
        report = response.json()

        assert report["bot_id"] == bot["id"]
        assert report["status"] == "ok"
        assert report["errors"] == []
        assert len(report["signals"]) == 1
        assert report["signals"][0]["side"] == "buy"
        assert len(report["decisions"]) == 1
        assert report["decisions"][0]["approved"] is True
        assert len(report["orders"]) == 1
        order = report["orders"][0]
        assert order["status"] == "filled"
        assert order["quantity"] == report["decisions"][0]["max_size_allowed"]
        assert order["quantity"] > 0

        # the report is persisted and queryable
        cycles = client.get(f"/bots/{bot['id']}/cycles").json()
        assert len(cycles) == 1
        assert cycles[0]["id"] == report["id"]
        assert cycles[0]["orders"] == report["orders"]

    # downstream effects are real: execution persisted, position exists
    executions = platform.get_json(
        platform.execution_http, "/executions", params={"account_id": ACCOUNT}
    )
    assert len(executions) == 1
    assert executions[0]["order_id"] == order["order_id"]

    state = platform.get_json(platform.portfolio_http, f"/portfolio/{ACCOUNT}")
    positions = {p["symbol"]: p for p in state["positions"]}
    assert SYMBOL in positions
    assert positions[SYMBOL]["quantity"] == order["filled_quantity"]
    assert state["account"]["balance"] < 100_000.0


def test_run_once_rejection_via_api(platform):
    from fastapi.testclient import TestClient

    platform.bars_by_symbol[SYMBOL] = synthetic_uptrend_bars(symbol=SYMBOL)
    headers = auth_headers(["trader"])

    # tighten the account's real risk limits so the signal is rejected
    limits = platform.get_json(platform.risk_http, f"/risk/limits/{ACCOUNT}")["limits"]
    limits["max_risk_per_trade"] = 1e-9

    async def _put():
        response = await platform.risk_http.put(
            f"/risk/limits/{ACCOUNT}", json=limits, headers=auth_headers(["admin"])
        )
        assert response.status_code == 200, response.text

    platform.run(_put())

    with TestClient(platform.trading.app) as client:
        bot = client.post("/bots", json=_bot_payload(), headers=headers).json()
        report = client.post(f"/bots/{bot['id']}/run-once", headers=headers).json()

    assert len(report["signals"]) == 1
    assert report["decisions"][0]["approved"] is False
    assert report["orders"] == []

    executions = platform.get_json(
        platform.execution_http, "/executions", params={"account_id": ACCOUNT}
    )
    assert executions == []
