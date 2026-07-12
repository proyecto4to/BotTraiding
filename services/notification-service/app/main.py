"""notification-service — Fase 16: real alerting service.

Responsabilidad (docs/ARCHITECTURE.md seccion 3): alertas (email/telegram/
webhook) sobre eventos de riesgo, ejecucion y sistema.

Intake:  NATS subscriber (risk.>, execution.>, ai.>, optimizer.>, bot.> by
         default; degraded mode when NATS is unavailable) + internal REST
         fallback POST /notifications/ingest.
Routing: app/rules.py derives severity; app/routing.py matches per-user
         persisted preferences (subjects, accounts, per-channel min-severity)
         and dispatches through app/channels/* with retry + dead-lettering.
API:     GET /notifications (JWT; users see their own, admin sees all),
         GET/PUT /preferences/{user_id} (own or admin),
         POST /notifications/test (admin), /health, /ready.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, events, routing
from app.channels import get_senders
from app.db import get_db
from app.deps import get_token_payload, is_admin, require_admin
from app.models import NotificationRow, PreferenceRow
from app.schemas import (
    EventIn,
    IngestResponse,
    NotificationOut,
    PreferencesIn,
    PreferencesOut,
    TestSendIn,
    TestSendResponse,
)
from trading_contracts.auth import TokenPayload

logger = logging.getLogger("notification-service")

SERVICE_NAME = "notification-service"

MAX_LIST_LIMIT = 500


@asynccontextmanager
async def lifespan(app: FastAPI):
    await events.start(app)
    yield
    await events.stop(app)


app = FastAPI(title="notification-service", version="0.2.0", lifespan=lifespan)

# Fase 14 (Monitoreo): default HTTP metrics (request count/latency/errors,
# in-progress gauge) exposed on /metrics for Prometheus. Guarded so repeated
# imports (tests) never register duplicate collectors.
if not getattr(app.state, "metrics_instrumented", False):
    Instrumentator(
        should_instrument_requests_inprogress=True,
        inprogress_labels=False,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, include_in_schema=False)
    app.state.metrics_instrumented = True


@app.get("/health")
def health() -> dict:
    """Liveness probe: the process is up."""
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    """Readiness probe. NATS being down does NOT flip readiness: the service
    deliberately runs degraded (REST intake + API still work)."""
    nats_state = getattr(app.state, "nats", None)
    connected = bool(nats_state and nats_state.connected)
    return {
        "status": "ready",
        "service": SERVICE_NAME,
        "nats_connected": connected,
        "mode": "full" if connected else "degraded",
        "subjects": list(nats_state.subjects) if nats_state else config.subjects(),
    }


# ---------------------------------------------------------------------------
# Intake (internal REST fallback for services without NATS access)
# ---------------------------------------------------------------------------


@app.post(
    "/notifications/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest(
    event: EventIn,
    db: Session = Depends(get_db),
    x_internal_token: str | None = Header(default=None),
) -> IngestResponse:
    """Internal intake: same pipeline as the NATS subscriber. Optionally
    guarded by NOTIFY_INGEST_TOKEN (X-Internal-Token header); open on the
    internal network when unset, like other service-to-service seams."""
    expected = config.ingest_token()
    if expected is not None and x_internal_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad ingest token")
    rows = await routing.ingest_event(db, event)
    return IngestResponse(accepted=True, notification_ids=[row.id for row in rows])


# ---------------------------------------------------------------------------
# Notifications feed (dashboard alerts page polls this)
# ---------------------------------------------------------------------------


@app.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    user_id: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIST_LIMIT),
    token: TokenPayload = Depends(get_token_payload),
    db: Session = Depends(get_db),
) -> list[NotificationOut]:
    """Newest first. Non-admins only ever see their own rows; admin sees all
    and may filter by user_id."""
    if not is_admin(token):
        if user_id is not None and user_id != token.sub:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot read another user's notifications",
            )
        user_id = token.sub

    query = select(NotificationRow)
    if user_id is not None:
        query = query.where(NotificationRow.user_id == user_id)
    if severity is not None:
        query = query.where(NotificationRow.severity == severity)
    query = query.order_by(NotificationRow.created_at.desc(), NotificationRow.id).limit(limit)
    rows = db.execute(query).scalars().all()
    return [NotificationOut.model_validate(row) for row in rows]


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------


def _require_self_or_admin(user_id: str, token: TokenPayload) -> None:
    if token.sub != user_id and not is_admin(token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot access another user's preferences",
        )


@app.get("/preferences/{user_id}", response_model=PreferencesOut)
def get_preferences(
    user_id: str,
    token: TokenPayload = Depends(get_token_payload),
    db: Session = Depends(get_db),
) -> PreferencesOut:
    """Defaults (everything disabled) when the user has no row yet, so the
    frontend settings page can always render."""
    _require_self_or_admin(user_id, token)
    row = db.get(PreferenceRow, user_id)
    if row is None:
        return PreferencesOut(user_id=user_id)
    return PreferencesOut.model_validate(row)


@app.put("/preferences/{user_id}", response_model=PreferencesOut)
def put_preferences(
    user_id: str,
    prefs: PreferencesIn,
    token: TokenPayload = Depends(get_token_payload),
    db: Session = Depends(get_db),
) -> PreferencesOut:
    _require_self_or_admin(user_id, token)
    row = db.get(PreferenceRow, user_id)
    if row is None:
        row = PreferenceRow(user_id=user_id)
        db.add(row)
    for field_name, value in prefs.model_dump().items():
        setattr(row, field_name, value)
    db.commit()
    db.refresh(row)
    return PreferencesOut.model_validate(row)


# ---------------------------------------------------------------------------
# Admin: test send
# ---------------------------------------------------------------------------


@app.post("/notifications/test", response_model=TestSendResponse)
async def test_send(
    request: TestSendIn,
    admin: TokenPayload = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TestSendResponse:
    """Admin-only: push a test message through one channel using the target
    user's stored preferences (bypasses enable/min-severity gates so a channel
    can be verified before enabling it)."""
    pref = db.get(PreferenceRow, request.user_id)
    if pref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No preferences stored for user {request.user_id}",
        )
    sender = get_senders().get(request.channel)
    if sender is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown channel")

    row = NotificationRow(
        user_id=request.user_id,
        subject="notification.test",
        severity="info",
        title="Test notification",
        body=request.message,
        payload={"requested_by": admin.sub, "channel": request.channel},
        status="pending",
    )
    db.add(row)
    db.flush()

    error: str | None = None
    try:
        await routing.send_with_retry(sender, routing.notification_dict(row), pref)
        row.status = "sent"
    except routing.DeliveryError as exc:
        row.status = "dead"
        error = str(exc)
        from app.models import DeadLetterRow

        db.add(
            DeadLetterRow(
                notification_id=row.id,
                user_id=row.user_id,
                channel=request.channel,
                target=routing._channel_target(pref, request.channel),
                error=error,
                retry_count=exc.attempts,
                payload=routing.notification_dict(row),
            )
        )
    db.commit()
    return TestSendResponse(
        notification_id=row.id, channel=request.channel, status=row.status, error=error
    )
