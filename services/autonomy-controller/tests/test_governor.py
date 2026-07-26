"""P5 — strategy lifecycle governor: the AI's advice acts under guardrails."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db as db_module
from app import governor
from app import statemachine as sm


def _session():
    return db_module.SessionLocal()


def _iso(minutes_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _disable_rec(key="sma_crossover", minutes_ago=5.0, rec_id=1):
    return {
        "id": rec_id,
        "strategy_key": key,
        "action": "disable",
        "rule": "rolling_sharpe_below_threshold",
        "reason": "rolling Sharpe below the threshold",
        "severity": "high",
        "metrics": {},
        "created_at": _iso(minutes_ago),
    }


# --- disable: only on a validated, fresh recommendation ----------------------


async def test_active_mode_disables_on_fresh_recommendation(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.ai.recommendations_value = [_disable_rec()]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], [])
        rows = governor.recent_actions(db, 10)

    assert fake_clients.strategies.toggled == [("sma_crossover", False)]
    assert [a["status"] for a in actions] == ["applied"]
    assert rows[0].action == "disable" and rows[0].status == "applied"
    assert rows[0].rule == "rolling_sharpe_below_threshold"
    assert rows[0].recommendation_id == "1"


async def test_shadow_mode_records_but_never_touches_the_catalog(fake_clients):
    # shadow is the default mode: no env var set in conftest.
    fake_clients.ai.recommendations_value = [_disable_rec()]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], [])
        rows = governor.recent_actions(db, 10)

    assert fake_clients.strategies.toggled == []
    assert [a["status"] for a in actions] == ["shadow"]
    # Audited even in shadow: the operator can inspect what WOULD happen.
    assert rows[0].status == "shadow" and rows[0].mode == "shadow"


async def test_never_disables_without_a_recommendation(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], [])
    assert actions == []
    assert fake_clients.strategies.toggled == []


async def test_stale_recommendation_is_ignored(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.ai.recommendations_value = [
        _disable_rec(minutes_ago=60 * 48)  # 2 days > the 24h default max age
    ]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], [])
    assert actions == [] and fake_clients.strategies.toggled == []


async def test_recommendation_without_timestamp_is_never_acted_on(
    fake_clients, monkeypatch
):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    rec = _disable_rec()
    rec.pop("created_at")
    fake_clients.ai.recommendations_value = [rec]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], [])
    assert actions == [] and fake_clients.strategies.toggled == []


async def test_unknown_strategy_is_never_touched(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.ai.recommendations_value = [_disable_rec(key="not_in_catalog")]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], [])
    assert actions == [] and fake_clients.strategies.toggled == []


# --- enable: regime-favored, disabled, and no standing disable rec ------------


async def test_enables_regime_favored_disabled_strategy(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.strategies.catalog["rsi2_reversion"] = False
    selection = [{"symbol": "BTCUSDT", "strategy_key": "rsi2_reversion", "weight": 1.0}]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, selection, [])

    assert fake_clients.strategies.toggled == [("rsi2_reversion", True)]
    assert actions[0]["action"] == "enable" and actions[0]["status"] == "applied"


async def test_no_enable_while_a_fresh_disable_recommendation_stands(
    fake_clients, monkeypatch
):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.strategies.catalog["rsi2_reversion"] = False
    fake_clients.ai.recommendations_value = [_disable_rec(key="rsi2_reversion")]
    selection = [{"symbol": "BTCUSDT", "strategy_key": "rsi2_reversion", "weight": 1.0}]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, selection, [])
    assert actions == [] and fake_clients.strategies.toggled == []


# --- guardrails: change cap + per-window dedup --------------------------------


async def test_change_cap_per_window_is_respected(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MAX_CHANGES", "1")
    fake_clients.ai.recommendations_value = [
        _disable_rec(key="sma_crossover", rec_id=1),
        _disable_rec(key="rsi2_reversion", rec_id=2),
    ]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], [])

    assert len(fake_clients.strategies.toggled) == 1  # only ONE applied
    statuses = {a["strategy_key"]: a["status"] for a in actions}
    assert sorted(statuses.values()) == ["applied", "capped"]


async def test_same_decision_is_not_repeated_within_the_window(fake_clients):
    fake_clients.ai.recommendations_value = [_disable_rec()]
    with _session() as db:
        first = await governor.run_governor(db, fake_clients, [], [])
        second = await governor.run_governor(db, fake_clients, [], [])
        rows = governor.recent_actions(db, 10)

    assert len(first) == 1 and second == []
    assert len(rows) == 1  # one audit row, not one per tick


# --- modes and degradation ----------------------------------------------------


async def test_off_mode_does_nothing(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "off")
    fake_clients.ai.recommendations_value = [_disable_rec()]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], [])
    assert actions == []
    assert fake_clients.strategies.list_calls == 0  # no downstream traffic


async def test_unknown_mode_degrades_to_shadow(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "aggressive")
    fake_clients.ai.recommendations_value = [_disable_rec()]
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], [])
    assert [a["status"] for a in actions] == ["shadow"]
    assert fake_clients.strategies.toggled == []


async def test_recommendations_outage_is_isolated(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.ai.fail_recommendations = True
    errors: list = []
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], errors)
    assert actions == []
    assert errors and errors[0]["stage"] == "governor_recommendations"


async def test_catalog_outage_is_isolated(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.strategies.fail = True
    fake_clients.ai.recommendations_value = [_disable_rec()]
    errors: list = []
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], errors)
    assert actions == []
    assert errors and errors[0]["stage"] == "governor_strategies"


async def test_apply_failure_is_recorded_and_audited(fake_clients, monkeypatch):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.strategies.fail_toggle = True
    fake_clients.ai.recommendations_value = [_disable_rec()]
    errors: list = []
    with _session() as db:
        actions = await governor.run_governor(db, fake_clients, [], errors)
        rows = governor.recent_actions(db, 10)
    assert [a["status"] for a in actions] == ["failed"]
    assert rows[0].status == "failed"
    assert errors and errors[0]["stage"] == "governor_apply"


# --- integration: the tick drives the governor; the endpoint reports ----------


async def test_tick_runs_governor_and_endpoint_reports(
    client, fake_clients, admin_headers, service_headers, monkeypatch
):
    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.ai.recommendations_value = [_disable_rec()]

    assert client.post("/autonomy/enable", headers=admin_headers).status_code == 200
    tick = client.post("/autonomy/tick", headers=service_headers)
    assert tick.status_code == 200
    body = tick.json()
    assert any(
        a["action"] == "disable" and a["status"] == "applied" for a in body["governor"]
    )
    assert fake_clients.strategies.toggled == [("sma_crossover", False)]

    status = client.get("/autonomy/governor")
    assert status.status_code == 200
    payload = status.json()
    assert payload["mode"] == "active"
    assert payload["actions"][0]["strategy_key"] == "sma_crossover"
    assert payload["actions"][0]["status"] == "applied"


async def test_governor_endpoint_defaults_to_shadow_and_empty(client):
    payload = client.get("/autonomy/governor").json()
    assert payload["mode"] == "shadow"
    assert payload["actions"] == []
    assert payload["max_changes_per_window"] >= 1


async def test_governor_skipped_when_automation_is_off(fake_clients, monkeypatch):
    """run_cycle in OFF never reaches the governor (no catalog traffic)."""
    from app import controller

    monkeypatch.setenv("AUTONOMY_GOVERNOR_MODE", "active")
    fake_clients.ai.recommendations_value = [_disable_rec()]
    with _session() as db:
        sm.get_state(db)  # OFF
        result = await controller.run_cycle(db, fake_clients)
    assert result.acted is False
    assert fake_clients.strategies.list_calls == 0
    assert fake_clients.strategies.toggled == []
