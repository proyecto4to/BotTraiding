"""Manual trigger endpoint: admin-only auth + job handlers with mocked
downstream clients."""

from __future__ import annotations

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


def test_reoptimize_never_asks_for_promotion() -> None:
    """The exploratory reoptimize job must never carry promote=true — and
    promote can never be smuggled in through job params: it is decided by
    the job TYPE (only the learning loop passes promote=True in code)."""
    from datetime import datetime, timedelta

    from app.clients import build_optimize_payload

    payload = build_optimize_payload(
        "sma_crossover",
        {"budget": 8, "lookback_days": 90, "promote": True},  # ignored on purpose
    )
    assert payload["promote"] is False
    assert payload["strategy_key"] == "sma_crossover"
    assert payload["budget"] == 8
    start = datetime.fromisoformat(payload["start"])
    end = datetime.fromisoformat(payload["end"])
    assert end - start == timedelta(days=90)


def test_learning_loop_payload_requests_gated_promotion() -> None:
    from app.clients import build_optimize_payload

    payload = build_optimize_payload("sma_crossover", {"budget": 8}, promote=True)
    assert payload["promote"] is True


# --- learning loop (P6): reoptimize -> gated promotion -> feedback ------------


def test_learning_loop_chains_reoptimize_promotion_and_feedback(
    client, admin_headers
) -> None:
    """The full chain with mocked downstreams: per enabled strategy the loop
    requests a gated promotion; a run whose OOS gate passed comes back
    applied and is reported as the new active config."""
    clients.set_strategy_engine(FakeStrategyEngineClient(["sma_crossover"]))
    fake_opt = FakeOptimizerClient(
        results={
            "sma_crossover": {
                "id": "run-ok",
                "status": "completed",
                "promoted": True,
                "applied": True,
                "best_params": {"fast": 12, "slow": 48},
            }
        }
    )
    clients.set_optimizer(fake_opt)

    body = client.post("/jobs/learning-loop/trigger", headers=admin_headers).json()
    assert body["status"] == "ok"
    result = body["result"]
    assert fake_opt.promote_flags == [True]  # the loop asks for gated promotion
    assert result["applied"] == [
        {
            "strategy_key": "sma_crossover",
            "run_id": "run-ok",
            "params": {"fast": 12, "slow": 48},
        }
    ]
    assert result["rejected"] == [] and result["errors"] == []


def test_learning_loop_oos_failure_is_not_promoted(client, admin_headers) -> None:
    """An improvement that does not beat the baseline out-of-sample is
    rejected by the optimizer's gate and NEVER applied."""
    clients.set_strategy_engine(FakeStrategyEngineClient(["rsi_reversion"]))
    fake_opt = FakeOptimizerClient(
        results={
            "rsi_reversion": {
                "id": "run-bad",
                "status": "completed",
                "promoted": False,
                "applied": False,
                "decision": {"reasons": ["candidate OOS sharpe below baseline"]},
            }
        }
    )
    clients.set_optimizer(fake_opt)

    result = client.post(
        "/jobs/learning-loop/trigger", headers=admin_headers
    ).json()["result"]
    assert result["applied"] == []
    assert result["rejected"] == [
        {
            "strategy_key": "rsi_reversion",
            "run_id": "run-bad",
            "reasons": ["candidate OOS sharpe below baseline"],
        }
    ]


def test_learning_loop_background_run_reported_in_progress(
    client, admin_headers
) -> None:
    clients.set_strategy_engine(FakeStrategyEngineClient(["slow_strategy"]))
    clients.set_optimizer(FakeOptimizerClient())  # default: status pending

    result = client.post(
        "/jobs/learning-loop/trigger", headers=admin_headers
    ).json()["result"]
    assert result["in_progress"] == [
        {"strategy_key": "slow_strategy", "run_id": "run-1"}
    ]
    assert result["applied"] == [] and result["rejected"] == []


def test_learning_loop_isolates_per_strategy_failures(client, admin_headers) -> None:
    clients.set_strategy_engine(FakeStrategyEngineClient(["good", "bad"]))
    fake_opt = FakeOptimizerClient(
        fail_for={"bad"},
        results={
            "good": {
                "id": "run-good",
                "status": "completed",
                "promoted": True,
                "applied": True,
                "best_params": {"x": 1},
            }
        },
    )
    clients.set_optimizer(fake_opt)

    result = client.post(
        "/jobs/learning-loop/trigger", headers=admin_headers
    ).json()["result"]
    assert [a["strategy_key"] for a in result["applied"]] == ["good"]
    assert [e["strategy_key"] for e in result["errors"]] == ["bad"]
