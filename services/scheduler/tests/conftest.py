"""Shared pytest fixtures: JWT secret for the admin-only trigger endpoint,
APScheduler autostart disabled (jobs run only via explicit trigger), and
clean downstream-client injection seams per test."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ["SCHEDULER_AUTOSTART"] = "false"
os.environ.pop("SCHEDULER_JOBS", None)

import pytest
from app import clients, jobs
from jose import jwt


@pytest.fixture(autouse=True)
def _reset_seams():
    clients.set_strategy_engine(None)
    clients.set_optimizer(None)
    clients.set_ai_engine(None)
    clients.set_health(None)
    jobs.last_runs.clear()
    yield
    clients.set_strategy_engine(None)
    clients.set_optimizer(None)
    clients.set_ai_engine(None)
    clients.set_health(None)
    jobs.last_runs.clear()


@pytest.fixture()
def client():
    from app.main import app
    from fastapi.testclient import TestClient

    # context manager runs the lifespan (loads the job registry)
    with TestClient(app) as test_client:
        yield test_client


def make_token(roles: list[str], token_type: str = "access") -> str:
    payload = {
        "sub": "00000000-0000-0000-0000-000000000099",
        "roles": roles,
        "type": token_type,
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


@pytest.fixture()
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(['admin'])}"}


@pytest.fixture()
def trader_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(['trader'])}"}
