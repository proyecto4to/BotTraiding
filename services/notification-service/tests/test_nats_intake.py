"""NATS intake: degraded mode when unavailable + message handler pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import events
from app.channels import set_senders
from app.models import NotificationRow
from tests.conftest import FakeSender, make_pref


def test_degraded_without_nats_url(monkeypatch, db_session) -> None:
    """NATS_URL unset: service starts, reports degraded, REST intake works."""
    monkeypatch.delenv("NATS_URL", raising=False)
    set_senders({})
    from app.main import app

    with TestClient(app) as client:  # context manager runs the lifespan
        ready = client.get("/ready").json()
        assert ready["status"] == "ready"
        assert ready["nats_connected"] is False
        assert ready["mode"] == "degraded"
        assert "risk.>" in ready["subjects"]

        response = client.post(
            "/notifications/ingest", json={"subject": "risk.rejected", "payload": {}}
        )
        assert response.status_code == 202


def test_degraded_when_nats_unreachable(monkeypatch, db_session) -> None:
    """NATS_URL set but nothing listening: warn + degrade, never crash."""
    monkeypatch.setenv("NATS_URL", "nats://127.0.0.1:59999")
    set_senders({})
    from app.main import app

    with TestClient(app) as client:
        ready = client.get("/ready").json()
        assert ready["status"] == "ready"
        assert ready["nats_connected"] is False
        assert ready["mode"] == "degraded"
        assert app.state.nats.error

        response = client.post(
            "/notifications/ingest", json={"subject": "bot.started", "payload": {}}
        )
        assert response.status_code == 202


def test_custom_subjects_env(monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_SUBJECTS", "risk.>, custom.topic")
    from app import config

    assert config.subjects() == ["risk.>", "custom.topic"]


# ---------------------------------------------------------------------------
# message handler: NATS message -> persisted -> routed
# ---------------------------------------------------------------------------


@dataclass
class FakeMsg:
    subject: str
    data: bytes


async def test_handle_message_persists_and_routes(db_session) -> None:
    pref = make_pref(subjects=["execution.>"], email="a@x.com")
    db_session.add(pref)
    db_session.commit()
    sender = FakeSender("email")
    set_senders({"email": sender})

    payload = {"symbol": "AAPL", "account_id": "acc-1", "status": "filled"}
    await events._handle_message(
        FakeMsg(subject="execution.report", data=json.dumps(payload).encode())
    )

    row = db_session.execute(select(NotificationRow)).scalars().one()
    assert row.user_id == pref.user_id
    assert row.subject == "execution.report"
    assert row.severity == "info"
    assert row.status == "sent"
    assert len(sender.calls) == 1


async def test_handle_message_poison_payload_never_raises(db_session) -> None:
    set_senders({})
    await events._handle_message(FakeMsg(subject="bot.x", data=b"\xff\xfenot json"))
    row = db_session.execute(select(NotificationRow)).scalars().one()
    assert row.subject == "bot.x"
    assert "raw" in row.payload


async def test_handle_message_swallow_routing_errors(db_session, monkeypatch) -> None:
    """Even if the pipeline itself explodes, the subscription callback survives."""

    async def _boom(db, event):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr("app.routing.ingest_event", _boom)
    await events._handle_message(FakeMsg(subject="risk.rejected", data=b"{}"))  # no raise
