"""P0 — order idempotency and startup stale-marking (architecture 2.6).

Covers the guarantees added for pre-live safety:
- child client_order_ids are deterministic (stable across process restarts),
- a transient-error retry re-places under the SAME client_order_id (so a
  venue that dedupes by it can never double-fill) and yields exactly one
  persisted report + one portfolio forward,
- in-flight executions found stale at startup are marked ``unknown`` and are
  reachable via GET /executions?status=unknown.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import db as db_module
from app import pipeline
from app.models import ChildOrderRow, ExecutionRow
from app.retry import TransientTransportError

from .conftest import full_fill, make_execution_payload


def test_child_client_order_id_is_deterministic_and_venue_sized():
    a = pipeline.child_client_order_id("exec-1", 0)
    b = pipeline.child_client_order_id("exec-1", 0)
    c = pipeline.child_client_order_id("exec-1", 1)
    d = pipeline.child_client_order_id("exec-2", 0)

    assert a == b  # same execution + sequence -> same key, forever
    assert a != c and a != d  # different sequence / execution -> different key
    assert len(a) <= 36  # fits the Binance clientOrderId limit


def test_retry_reuses_same_client_order_id_and_forwards_once(harness):
    """Two transient failures then success: all three attempts hit the venue
    with the identical order id, and only one fill is persisted/forwarded."""
    calls: list[str] = []

    def flaky(order, market_price):
        calls.append(str(order.id))
        if len(calls) < 3:
            return TransientTransportError("network blip")
        return full_fill(order, market_price)

    harness.paper.behavior = flaky

    response = harness.client.post("/executions", json=make_execution_payload())
    assert response.status_code == 201
    body = response.json()

    # Same idempotency key across every retry attempt — never a fresh id.
    assert len(calls) == 3
    assert set(calls) == {calls[0]}

    # Exactly one report and one portfolio forward despite the retries.
    assert body["status"] == "filled"
    assert len(body["reports"]) == 1
    assert len(harness.forwarder.calls) == 1
    child = body["child_orders"][0]
    assert child["attempts"] == 3
    assert calls[0] == child["client_order_id"]


def _insert_execution(session, *, status: str, updated_at: datetime, child_status: str):
    execution = ExecutionRow(
        order_id="ord-stale",
        signal_id="sig-stale",
        account_id="acct-stale",
        symbol="BTCUSD",
        side="buy",
        quantity=1.0,
        order_type="market",
        price=None,
        broker="binance",
        execution_mode="paper",
        status=status,
        created_at=updated_at,
        updated_at=updated_at,
    )
    session.add(execution)
    session.flush()
    session.add(
        ChildOrderRow(
            id=f"child-{execution.id}",
            client_order_id=f"child-{execution.id}",
            execution_id=execution.id,
            sequence=0,
            quantity=1.0,
            status=child_status,
        )
    )
    session.flush()
    return execution


def test_stale_inflight_marked_unknown_recent_left_alone(_test_db):
    now = datetime(2026, 1, 1, 12, 0, 0)
    with db_module.SessionLocal() as session:
        stale = _insert_execution(
            session,
            status="submitted",
            updated_at=now - timedelta(hours=1),
            child_status="submitted",
        )
        fresh = _insert_execution(
            session,
            status="submitted",
            updated_at=now - timedelta(seconds=10),
            child_status="submitted",
        )
        session.commit()
        stale_id, fresh_id = stale.id, fresh.id

        marked = pipeline.mark_stale_executions(
            session, stale_after_seconds=900, now=now
        )
        session.commit()

        assert [m["execution_id"] for m in marked] == [stale_id]
        assert session.get(ExecutionRow, stale_id).status == "unknown"
        assert session.get(ExecutionRow, fresh_id).status == "submitted"
        stale_child = pipeline.children_of(session, stale_id)[0]
        assert stale_child.status == "unknown"


def test_unknown_executions_are_listed(harness):
    now = datetime(2026, 1, 1, 12, 0, 0)
    with db_module.SessionLocal() as session:
        _insert_execution(
            session,
            status="unknown",
            updated_at=now,
            child_status="unknown",
        )
        session.commit()

    response = harness.client.get("/executions", params={"status": "unknown"})
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "unknown"
    assert rows[0]["account_id"] == "acct-stale"
