"""Job registry (env-config), GET /jobs, and cron next-run computation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.config import default_jobs, load_jobs
from app.runtime import cron_trigger, next_run_time, runtime


def test_default_registry_has_the_three_periodic_jobs() -> None:
    jobs = default_jobs()
    by_id = {j.id: j for j in jobs}
    assert set(by_id) == {"reoptimize-weekly", "regime-refresh-hourly", "health-ping"}
    assert by_id["reoptimize-weekly"].type == "reoptimize"
    assert by_id["reoptimize-weekly"].cron == "0 3 * * 1"  # weekly
    assert by_id["regime-refresh-hourly"].cron == "0 * * * *"  # hourly
    assert all(j.enabled for j in jobs)


def test_cron_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("REOPTIMIZE_CRON", "30 4 * * 6")
    jobs = {j.id: j for j in default_jobs()}
    assert jobs["reoptimize-weekly"].cron == "30 4 * * 6"


def test_scheduler_jobs_env_json(monkeypatch) -> None:
    monkeypatch.setenv(
        "SCHEDULER_JOBS",
        json.dumps(
            [
                {"id": "custom", "type": "health_ping", "cron": "*/10 * * * *"},
                {
                    "id": "paused",
                    "type": "reoptimize",
                    "cron": "0 0 * * 0",
                    "enabled": False,
                    "params": {"budget": 8},
                },
            ]
        ),
    )
    jobs = load_jobs()
    assert [j.id for j in jobs] == ["custom", "paused"]
    assert jobs[1].enabled is False
    assert jobs[1].params == {"budget": 8}


def test_scheduler_jobs_env_rejects_duplicates_and_non_arrays(monkeypatch) -> None:
    monkeypatch.setenv(
        "SCHEDULER_JOBS",
        json.dumps(
            [
                {"id": "x", "type": "health_ping", "cron": "* * * * *"},
                {"id": "x", "type": "health_ping", "cron": "* * * * *"},
            ]
        ),
    )
    with pytest.raises(ValueError, match="duplicate job id"):
        load_jobs()
    monkeypatch.setenv("SCHEDULER_JOBS", json.dumps({"id": "x"}))
    with pytest.raises(ValueError, match="JSON array"):
        load_jobs()


def test_next_run_time_matches_cron_and_none_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv(
        "SCHEDULER_JOBS",
        json.dumps(
            [
                {"id": "hourly", "type": "health_ping", "cron": "0 * * * *"},
                {
                    "id": "off",
                    "type": "health_ping",
                    "cron": "0 * * * *",
                    "enabled": False,
                },
            ]
        ),
    )
    hourly, off = load_jobs()
    nxt = next_run_time(hourly)
    assert nxt is not None
    now = datetime.now(timezone.utc)
    assert now < nxt
    assert nxt.minute == 0  # top of the hour
    assert (nxt - now).total_seconds() <= 3600
    assert next_run_time(off) is None


def test_cron_trigger_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        cron_trigger("not a cron")


def test_jobs_endpoint_lists_registry_with_next_runs(client) -> None:
    resp = client.get("/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert {j["id"] for j in jobs} == {
        "reoptimize-weekly", "regime-refresh-hourly", "health-ping",
    }
    for job in jobs:
        assert job["enabled"] is True
        assert job["next_run_time"] is not None
        assert job["last_run"] is None  # nothing has run yet


def test_jobs_endpoint_reflects_env_config(client, monkeypatch) -> None:
    monkeypatch.setenv(
        "SCHEDULER_JOBS",
        json.dumps([{"id": "only-one", "type": "health_ping", "cron": "*/5 * * * *"}]),
    )
    runtime.load()  # what the lifespan does on startup
    jobs = client.get("/jobs").json()
    assert [j["id"] for j in jobs] == ["only-one"]


def test_ready_reports_registry(client) -> None:
    body = client.get("/ready").json()
    assert body["status"] == "ready"
    assert body["jobs_loaded"] == 3
    assert body["clock_running"] is False  # SCHEDULER_AUTOSTART=false in tests
