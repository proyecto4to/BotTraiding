"""Manual trigger endpoint: admin-only auth + job handlers with mocked
downstream clients."""

from __future__ import annotations

import json

from app import clients

from tests.conftest import make_token
from tests.fakes import (
    FakeAiEngineClient,
    FakeHealthClient,
    FakeOptimizerClient,
    FakeStrategyEngineClient,
)

# --- authz ---------------------------------------------------------------------


def test_trigger_requires_token(client) -> None:
    resp = client.post("/jobs/health-ping/trigger")
    assert resp.status_code == 401


def test_trigger_rejects_non_admin(client, trader_headers) -> None:
    resp = client.post("/jobs/health-ping/trigger", headers=trader_headers)
    assert resp.status_code == 403


def test_trigger_rejects_refresh_tokens(client) -> None:
    headers = {"Authorization": f"Bearer {make_token(['admin'], token_type='refresh')}"}
    resp = client.post("/jobs/health-ping/trigger", headers=headers)
    assert resp.status_code == 401


def test_trigger_unknown_job_404(client, admin_headers) -> None:
    resp = client.post("/jobs/nope/trigger", headers=admin_headers)
    assert resp.status_code == 404


# --- job handlers via manual trigger -------------------------------------------


def test_reoptimize_triggers_one_run_per_enabled_strategy(client, admin_headers) -> None:
    fake_se = FakeStrategyEngineClient(["sma_crossover", "rsi_reversion"])
    fake_opt = FakeOptimizerClient()
    clients.set_strategy_engine(fake_se)
    clients.set_optimizer(fake_opt)

    resp = client.post("/jobs/reoptimize-weekly/trigger", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["result"]["strategies_seen"] == 2
    assert [t["strategy_key"] for t in body["result"]["triggered"]] == [
        "sma_crossover", "rsi_reversion",
    ]
    assert [k for k, _ in fake_opt.triggered] == ["sma_crossover", "rsi_reversion"]

    # the outcome is now visible on GET /jobs as last_run
    jobs = {j["id"]: j for j in client.get("/jobs").json()}
    assert jobs["reoptimize-weekly"]["last_run"]["status"] == "ok"


def test_reoptimize_isolates_per_strategy_failures(client, admin_headers) -> None:
    clients.set_strategy_engine(FakeStrategyEngineClient(["good", "bad"]))
    fake_opt = FakeOptimizerClient(fail_for={"bad"})
    clients.set_optimizer(fake_opt)

    body = client.post("/jobs/reoptimize-weekly/trigger", headers=admin_headers).json()
    assert body["status"] == "ok"
    assert [t["strategy_key"] for t in body["result"]["triggered"]] == ["good"]
    assert [e["strategy_key"] for e in body["result"]["errors"]] == ["bad"]


def test_regime_refresh_calls_ai_engine(client, admin_headers) -> None:
    fake_ai = FakeAiEngineClient()
    clients.set_ai_engine(fake_ai)

    resp = client.post("/jobs/regime-refresh-hourly/trigger", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["result"]["response"]["detail"] == "ok"
    assert len(fake_ai.calls) == 1


def test_health_ping_reports_down_services(client, admin_headers, monkeypatch) -> None:
    monkeypatch.setenv(
        "HEALTH_PING_URLS", "alpha=http://alpha:8000,beta=http://beta:8000"
    )
    fake_health = FakeHealthClient(down={"beta"})
    clients.set_health(fake_health)

    body = client.post("/jobs/health-ping/trigger", headers=admin_headers).json()
    assert body["status"] == "ok"
    assert body["result"]["statuses"] == {"alpha": True, "beta": False}
    assert body["result"]["down"] == ["beta"]
    assert ("alpha", "http://alpha:8000") in fake_health.pinged


def test_failing_job_returns_502_and_records_error(client, admin_headers) -> None:
    class ExplodingClient(FakeStrategyEngineClient):
        async def list_enabled_strategies(self):
            raise RuntimeError("strategy-engine is down")

    clients.set_strategy_engine(ExplodingClient([]))
    resp = client.post("/jobs/reoptimize-weekly/trigger", headers=admin_headers)
    assert resp.status_code == 502
    assert "strategy-engine is down" in resp.json()["detail"]

    jobs = {j["id"]: j for j in client.get("/jobs").json()}
    assert jobs["reoptimize-weekly"]["last_run"]["status"] == "error"


def test_scheduler_never_asks_for_promotion(client, admin_headers) -> None:
    """Cron re-optimization must never carry promote=true (Fase 12: only
    explicit, validated promotions may apply params)."""
    import inspect

    from app.clients import HttpOptimizerClient

    source = inspect.getsource(HttpOptimizerClient.trigger_optimization)
    assert '"promote": False' in source
