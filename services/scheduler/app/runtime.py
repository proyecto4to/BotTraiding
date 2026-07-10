"""APScheduler wiring for the periodic jobs (Fase 12).

The job REGISTRY (env-config, see config.py) is authoritative; APScheduler
is just the clock. ``next_run_time`` is computed from the cron expression
itself so GET /jobs works even when the background scheduler is not
running (e.g. under tests or SCHEDULER_AUTOSTART=false).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import JobDefinition, load_jobs
from .jobs import run_job

logger = logging.getLogger("scheduler.runtime")


def cron_trigger(expression: str) -> CronTrigger:
    """5-field crontab -> APScheduler trigger, evaluated in UTC."""
    return CronTrigger.from_crontab(expression, timezone="UTC")


def next_run_time(job: JobDefinition) -> Optional[datetime]:
    if not job.enabled:
        return None
    return cron_trigger(job.cron).get_next_fire_time(
        None, datetime.now(timezone.utc)
    )


class SchedulerRuntime:
    """Owns the loaded job registry + the (optional) APScheduler instance."""

    def __init__(self) -> None:
        self.jobs: list[JobDefinition] = []
        self._scheduler: Optional[AsyncIOScheduler] = None

    def load(self) -> None:
        self.jobs = load_jobs()
        logger.info("loaded %d job definitions", len(self.jobs))

    def get_job(self, job_id: str) -> Optional[JobDefinition]:
        return next((j for j in self.jobs if j.id == job_id), None)

    @property
    def running(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    def start(self) -> None:
        """Start the cron clock (must be called inside a running loop)."""
        if self.running:
            return
        scheduler = AsyncIOScheduler(timezone="UTC")
        for job in self.jobs:
            if not job.enabled:
                continue
            scheduler.add_job(
                run_job,
                trigger=cron_trigger(job.cron),
                id=job.id,
                args=[job],
                max_instances=1,
                coalesce=True,
            )
        scheduler.start()
        self._scheduler = scheduler
        logger.info(
            "APScheduler started with %d enabled jobs",
            sum(1 for j in self.jobs if j.enabled),
        )

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None


def autostart_enabled() -> bool:
    return os.environ.get("SCHEDULER_AUTOSTART", "true").lower() != "false"


#: process-wide runtime, (re)loaded by the app lifespan.
runtime = SchedulerRuntime()
