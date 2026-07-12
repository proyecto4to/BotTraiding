"""Shared fixtures: in-memory SQLite wired into app.db (auth-service/
risk-engine pattern), test JWTs, and injectable fake channel senders."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.pop("NATS_URL", None)  # degraded mode by default in tests
os.environ["NOTIFY_RETRY_BACKOFF"] = "0"  # no sleeping in retry tests

import pytest
from jose import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app.channels import PermanentSendError, TransientSendError, set_senders
from app.models import Base, PreferenceRow


@pytest.fixture(autouse=True)
def _test_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _fk_pragma(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    db_module.engine = engine
    db_module.SessionLocal = TestSession

    yield

    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _reset_senders():
    set_senders(None)
    yield
    set_senders(None)


@pytest.fixture()
def db_session():
    with db_module.SessionLocal() as session:
        yield session


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def make_token(roles: list[str], sub: str | None = None, token_type: str = "access") -> str:
    payload = {
        "sub": sub or str(uuid.uuid4()),
        "roles": roles,
        "type": token_type,
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


def auth_headers(roles: list[str], sub: str | None = None) -> dict:
    return {"Authorization": f"Bearer {make_token(roles, sub=sub)}"}


@pytest.fixture()
def admin_headers():
    return auth_headers(["admin"])


class FakeSender:
    """Injectable ChannelSender: records calls, optionally fails.

    fail_times=N  -> first N sends raise TransientSendError, then succeed.
    permanent=True -> every send raises PermanentSendError immediately.
    """

    def __init__(self, name: str = "fake", fail_times: int = 0, permanent: bool = False):
        self.name = name
        self.fail_times = fail_times
        self.permanent = permanent
        self.calls: list[tuple[dict, object]] = []

    async def send(self, notification: dict, preference) -> None:
        self.calls.append((notification, preference))
        if self.permanent:
            raise PermanentSendError(f"{self.name}: permanent failure")
        if len(self.calls) <= self.fail_times:
            raise TransientSendError(f"{self.name}: transient failure #{len(self.calls)}")


def make_pref(
    user_id: str | None = None,
    subjects: list[str] | None = None,
    account_ids: list[str] | None = None,
    email: str | None = None,
    email_min: str = "info",
    telegram: str | None = None,
    telegram_min: str = "info",
    webhook: str | None = None,
    webhook_min: str = "info",
    webhook_secret: str | None = None,
) -> PreferenceRow:
    return PreferenceRow(
        user_id=user_id or str(uuid.uuid4()),
        subjects=subjects or [],
        account_ids=account_ids or [],
        email_enabled=email is not None,
        email_address=email,
        email_min_severity=email_min,
        telegram_enabled=telegram is not None,
        telegram_chat_id=telegram,
        telegram_min_severity=telegram_min,
        webhook_enabled=webhook is not None,
        webhook_url=webhook,
        webhook_secret=webhook_secret,
        webhook_min_severity=webhook_min,
    )
