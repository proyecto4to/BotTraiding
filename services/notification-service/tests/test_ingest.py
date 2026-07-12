"""REST intake: POST /notifications/ingest -> persisted -> routed."""

from __future__ import annotations

from sqlalchemy import select

from app.channels import set_senders
from app.models import NotificationRow
from tests.conftest import FakeSender, make_pref


def test_ingest_persists_and_routes(client, db_session) -> None:
    pref = make_pref(subjects=["risk.>"], email="trader@example.com")
    db_session.add(pref)
    db_session.commit()
    sender = FakeSender("email")
    set_senders({"email": sender})

    response = client.post(
        "/notifications/ingest",
        json={
            "subject": "risk.circuit_breaker",
            "account_id": "acc-1",
            "payload": {"state": "HARD_HALT", "account_id": "acc-1"},
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert len(body["notification_ids"]) == 1

    row = db_session.get(NotificationRow, body["notification_ids"][0])
    assert row is not None
    assert row.user_id == pref.user_id
    assert row.severity == "critical"  # derived by rules
    assert row.status == "sent"
    assert row.account_id == "acc-1"

    assert len(sender.calls) == 1
    notification, _ = sender.calls[0]
    assert notification["id"] == row.id
    assert notification["severity"] == "critical"


def test_ingest_explicit_severity_override(client, db_session) -> None:
    set_senders({})
    response = client.post(
        "/notifications/ingest",
        json={"subject": "bot.heartbeat", "severity": "warning", "payload": {}},
    )
    assert response.status_code == 202
    row = db_session.execute(select(NotificationRow)).scalars().one()
    assert row.severity == "warning"


def test_ingest_rejects_bad_event(client) -> None:
    assert client.post("/notifications/ingest", json={"payload": {}}).status_code == 422
    assert (
        client.post(
            "/notifications/ingest", json={"subject": "x", "severity": "catastrophic"}
        ).status_code
        == 422
    )


def test_ingest_delivery_failure_still_returns_202(client, db_session, monkeypatch) -> None:
    """A dead SMTP server must not turn intake into a 500."""
    monkeypatch.setenv("NOTIFY_MAX_RETRIES", "0")
    db_session.add(make_pref(email="a@x.com"))
    db_session.commit()
    set_senders({"email": FakeSender("email", fail_times=99)})

    response = client.post(
        "/notifications/ingest", json={"subject": "risk.rejected", "payload": {}}
    )
    assert response.status_code == 202
    row = db_session.execute(select(NotificationRow)).scalars().one()
    assert row.status == "dead"


def test_ingest_token_gate(client, monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_INGEST_TOKEN", "shh")
    set_senders({})

    denied = client.post("/notifications/ingest", json={"subject": "x", "payload": {}})
    assert denied.status_code == 401

    allowed = client.post(
        "/notifications/ingest",
        json={"subject": "x", "payload": {}},
        headers={"X-Internal-Token": "shh"},
    )
    assert allowed.status_code == 202
