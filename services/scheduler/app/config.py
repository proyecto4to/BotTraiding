"""Job configuration for the scheduler (Fase 12) - env-config, no DB.

Job definition format (env ``SCHEDULER_JOBS``, a JSON array):

    [
      {"id": "reoptimize-weekly",     # unique job id
       "type": "reoptimize",          # reoptimize | regime_refresh | health_ping
       "cron": "0 3 * * 1",           # standard 5-field crontab, UTC
       "enabled": true,               # disabled jobs are listed, never run
       "params": {"budget": 16}},     # optional per-type overrides
      ...
    ]

When SCHEDULER_JOBS is unset, five default jobs are created; their
schedules alone are overridable via REOPTIMIZE_CRON (default weekly,
Monday 03:00 UTC), LEARNING_LOOP_CRON (default daily, 04:00 UTC),
REGIME_REFRESH_CRON (default hourly), HEALTH_PING_CRON (default every
5 minutes) and AUTONOMY_TICK_CRON (default every 5 minutes).

Job types:
- ``reoptimize``: lists enabled strategies from strategy-engine and POSTs
  one /optimize run per strategy to the optimizer (never with
  promote=true from here - an exploratory scan that only reports).
  params: symbol, timeframe, lookback_days, search_type, budget.
- ``learning_loop`` (P6): the continuous-learning loop. Same per-strategy
  re-optimization but WITH gated promotion (promote=true): the optimizer
  only applies params that beat the baseline out-of-sample (walk-forward);
  the autonomy bots pick the new config up on their next evaluation.
  params: same as ``reoptimize``.
- ``regime_refresh``: POSTs /ai/regime/refresh to ai-engine.
- ``health_ping``: GETs /health on every downstream service.
- ``autonomy_tick``: POSTs /autonomy/tick to the autonomy-controller so the
  self-driving loop advances on a cadence (a no-op while the master switch
  is off).
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field

JobType = Literal[
    "reoptimize", "learning_loop", "regime_refresh", "health_ping", "autonomy_tick"
]


class JobDefinition(BaseModel):
    id: str
    type: JobType
    #: 5-field crontab expression, evaluated in UTC.
    cron: str
    enabled: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


def default_jobs() -> list[JobDefinition]:
    return [
        JobDefinition(
            id="reoptimize-weekly",
            type="reoptimize",
            cron=os.environ.get("REOPTIMIZE_CRON", "0 3 * * 1"),
        ),
        JobDefinition(
            id="learning-loop",
            type="learning_loop",
            cron=os.environ.get("LEARNING_LOOP_CRON", "0 4 * * *"),
        ),
        JobDefinition(
            id="regime-refresh-hourly",
            type="regime_refresh",
            cron=os.environ.get("REGIME_REFRESH_CRON", "0 * * * *"),
        ),
        JobDefinition(
            id="health-ping",
            type="health_ping",
            cron=os.environ.get("HEALTH_PING_CRON", "*/5 * * * *"),
        ),
        JobDefinition(
            id="autonomy-tick",
            type="autonomy_tick",
            cron=os.environ.get("AUTONOMY_TICK_CRON", "*/5 * * * *"),
        ),
    ]


def load_jobs() -> list[JobDefinition]:
    """Jobs from env SCHEDULER_JOBS (JSON) or the documented defaults."""
    raw = os.environ.get("SCHEDULER_JOBS", "").strip()
    if not raw:
        return default_jobs()
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("SCHEDULER_JOBS must be a JSON array of job objects")
    jobs = [JobDefinition.model_validate(item) for item in data]
    seen: set[str] = set()
    for job in jobs:
        if job.id in seen:
            raise ValueError(f"duplicate job id '{job.id}' in SCHEDULER_JOBS")
        seen.add(job.id)
    return jobs
