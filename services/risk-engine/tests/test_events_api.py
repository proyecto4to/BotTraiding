"""GET /risk/events/{account_id}: recent persisted risk_events, newest
first, paginated with limit/offset (polled by the frontend alerts page
through the gateway as /api/risk/events/{account})."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models import RiskEvent

BASE_TS = datetime(2026, 1, 1, 12, 0, 0)


def _seed_events(db_session, account_id: str = "acc-1", count: int = 5) -> list[RiskEvent]:
    """Insert `count` events with strictly increasing created_at."""
    rows = []
    for i in range(count):
        row = RiskEvent(
            account_id=account_id,
            event_type="risk.rejected" if i % 2 == 0 else "risk.circuit_breaker",
            signal_id=f"sig-{i}" if i % 2 == 0 else None,
            payload={"seq": i, "reason": "max_daily_loss"},
            created_at=BASE_TS + timedelta(minutes=i),
        )
        db_session.add(row)
        rows.append(row)
    db_session.commit()
    return rows


def test_events_empty_account_returns_empty_list(client):
    response = client.get("/risk/events/nobody")
    assert response.status_code == 200
    assert response.json() == []


def test_events_newest_first_with_row_shape(client, db_session):
    _seed_events(db_session, "acc-1", count=3)

    response = client.get("/risk/events/acc-1")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 3
    # Newest first: seq 2, 1, 0.
    assert [e["payload"]["seq"] for e in events] == [2, 1, 0]

    first = events[0]
    assert set(first) == {"id", "account_id", "event_type", "signal_id", "payload", "created_at"}
    assert first["account_id"] == "acc-1"
    assert first["event_type"] == "risk.rejected"
    assert first["signal_id"] == "sig-2"
    assert first["created_at"] is not None


def test_events_filtered_by_account(client, db_session):
    _seed_events(db_session, "acc-1", count=2)
    _seed_events(db_session, "acc-2", count=1)

    response = client.get("/risk/events/acc-2")
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert all(e["account_id"] == "acc-2" for e in events)


def test_events_pagination_limit_and_offset(client, db_session):
    _seed_events(db_session, "acc-1", count=5)

    page1 = client.get("/risk/events/acc-1", params={"limit": 2}).json()
    page2 = client.get("/risk/events/acc-1", params={"limit": 2, "offset": 2}).json()
    page3 = client.get("/risk/events/acc-1", params={"limit": 2, "offset": 4}).json()

    assert [e["payload"]["seq"] for e in page1] == [4, 3]
    assert [e["payload"]["seq"] for e in page2] == [2, 1]
    assert [e["payload"]["seq"] for e in page3] == [0]


def test_events_limit_is_validated(client):
    assert client.get("/risk/events/acc-1", params={"limit": 0}).status_code == 422
    assert client.get("/risk/events/acc-1", params={"limit": 9999}).status_code == 422
    assert client.get("/risk/events/acc-1", params={"offset": -1}).status_code == 422
