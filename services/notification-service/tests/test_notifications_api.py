"""GET /notifications (filters + user isolation) and POST /notifications/test."""

from __future__ import annotations

from app.channels import set_senders
from app.models import NotificationRow
from tests.conftest import FakeSender, auth_headers, make_pref


def _seed(db_session) -> None:
    db_session.add_all(
        [
            NotificationRow(
                user_id="user-a", subject="risk.rejected", severity="info",
                title="a1", body="", payload={}, status="sent",
            ),
            NotificationRow(
                user_id="user-a", subject="risk.circuit_breaker", severity="critical",
                title="a2", body="", payload={}, status="sent",
            ),
            NotificationRow(
                user_id="user-b", subject="execution.report", severity="info",
                title="b1", body="", payload={}, status="sent",
            ),
            NotificationRow(
                user_id=None, subject="bot.started", severity="info",
                title="broadcast", body="", payload={}, status="sent",
            ),
        ]
    )
    db_session.commit()


def test_requires_auth(client) -> None:
    assert client.get("/notifications").status_code == 401


def test_user_sees_only_own_rows(client, db_session) -> None:
    _seed(db_session)
    response = client.get("/notifications", headers=auth_headers(["trader"], sub="user-a"))
    assert response.status_code == 200
    rows = response.json()
    assert {row["title"] for row in rows} == {"a1", "a2"}
    # frontend contract: flat shape
    for row in rows:
        for key in ("id", "subject", "severity", "title", "body", "created_at", "status"):
            assert key in row


def test_user_cannot_query_other_user(client, db_session) -> None:
    _seed(db_session)
    response = client.get(
        "/notifications",
        params={"user_id": "user-b"},
        headers=auth_headers(["trader"], sub="user-a"),
    )
    assert response.status_code == 403


def test_severity_filter_and_limit(client, db_session) -> None:
    _seed(db_session)
    headers = auth_headers(["trader"], sub="user-a")
    critical = client.get(
        "/notifications", params={"severity": "critical"}, headers=headers
    ).json()
    assert [row["title"] for row in critical] == ["a2"]

    limited = client.get("/notifications", params={"limit": 1}, headers=headers).json()
    assert len(limited) == 1


def test_admin_sees_all_and_can_filter_by_user(client, db_session, admin_headers) -> None:
    _seed(db_session)
    everything = client.get("/notifications", headers=admin_headers).json()
    assert len(everything) == 4  # includes the broadcast row

    only_b = client.get(
        "/notifications", params={"user_id": "user-b"}, headers=admin_headers
    ).json()
    assert [row["title"] for row in only_b] == ["b1"]


# ---------------------------------------------------------------------------
# POST /notifications/test
# ---------------------------------------------------------------------------


def test_test_send_is_admin_only(client) -> None:
    body = {"user_id": "user-a", "channel": "email"}
    assert client.post("/notifications/test", json=body).status_code == 401
    assert (
        client.post(
            "/notifications/test", json=body, headers=auth_headers(["trader"], sub="user-a")
        ).status_code
        == 403
    )


def test_test_send_uses_chosen_channel(client, db_session, admin_headers) -> None:
    db_session.add(make_pref(user_id="user-a", telegram="chat-1"))
    db_session.commit()
    telegram = FakeSender("telegram")
    set_senders({"telegram": telegram, "email": FakeSender("email")})

    response = client.post(
        "/notifications/test",
        json={"user_id": "user-a", "channel": "telegram", "message": "ping"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"
    assert body["channel"] == "telegram"
    assert len(telegram.calls) == 1
    notification, _pref = telegram.calls[0]
    assert notification["body"] == "ping"
    assert notification["subject"] == "notification.test"
    assert notification["user_id"] == "user-a"

    row = db_session.get(NotificationRow, body["notification_id"])
    assert row is not None and row.status == "sent"


def test_test_send_unknown_user_404(client, admin_headers) -> None:
    response = client.post(
        "/notifications/test",
        json={"user_id": "ghost", "channel": "email"},
        headers=admin_headers,
    )
    assert response.status_code == 404


def test_test_send_failure_reports_dead(client, db_session, admin_headers, monkeypatch) -> None:
    monkeypatch.setenv("NOTIFY_MAX_RETRIES", "0")
    db_session.add(make_pref(user_id="user-a", email="a@x.com"))
    db_session.commit()
    set_senders({"email": FakeSender("email", fail_times=99)})

    response = client.post(
        "/notifications/test",
        json={"user_id": "user-a", "channel": "email"},
        headers=admin_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dead"
    assert body["error"]
