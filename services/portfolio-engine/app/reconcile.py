"""Startup/on-demand reconciliation of local portfolio state vs broker truth
(architecture principle 2.6: a crash must not leave orphan positions —
reconciliar al arrancar contra el broker).

Pieces
------
- ``HttpBrokerClient``: injectable client for broker-connectors
  (GET /connectors/{broker}/positions and /account). Tests inject fakes via
  the ``get_broker_client`` FastAPI dependency seam.
- ``build_report``: pure comparison — matched / missing_locally /
  missing_at_broker / quantity_mismatches, with RECONCILE_QTY_TOLERANCE
  absorbing fee dust (|broker - local| <= tolerance counts as matched).
- ``apply_report``: aligns local positions to broker truth, recording each
  adjustment as an auditable synthetic execution
  (portfolio_executions.source == "reconciliation", realized_pnl == 0,
  cash untouched: an inventory correction is not a trade).
- ``run_startup_reconciliation``: report-only pass at service startup when
  RECONCILE_ON_START=true (default false: it needs a connected broker
  session). NEVER applies automatically; discrepancies are logged loudly.

Env vars
--------
- RECONCILE_QTY_TOLERANCE: |broker qty - local qty| <= tolerance is a match
  (default 1e-8, fee-dust scale).
- BROKER_CONNECTORS_URL: broker-connectors base URL
  (default http://broker-connectors:8000).
- RECONCILE_TIMEOUT: HTTP timeout towards broker-connectors (default 10s).
- RECONCILE_ON_START: run a report-only reconciliation at startup
  (default false).
- RECONCILE_STARTUP_TARGETS: comma-separated "broker:account_id" pairs to
  reconcile at startup; the account_id is used both as the local portfolio
  account and the broker-connectors session account.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PortfolioExecution, PortfolioPosition
from app.schemas import (
    ReconcileEntry,
    ReconciliationAdjustment,
    ReconciliationReport,
)
from trading_contracts import AccountState, Position

logger = logging.getLogger("portfolio-engine.reconcile")

RECONCILIATION_SOURCE = "reconciliation"


# --- configuration (read at call time so tests can monkeypatch) -------------


def qty_tolerance() -> float:
    return float(os.environ.get("RECONCILE_QTY_TOLERANCE", "1e-8"))


def broker_connectors_url() -> str:
    return os.environ.get(
        "BROKER_CONNECTORS_URL", "http://broker-connectors:8000"
    ).rstrip("/")


def reconcile_timeout() -> float:
    return float(os.environ.get("RECONCILE_TIMEOUT", "10"))


def reconcile_on_start() -> bool:
    return os.environ.get("RECONCILE_ON_START", "false").lower() in ("1", "true", "yes")


def startup_targets() -> list[tuple[str, str]]:
    """Parse RECONCILE_STARTUP_TARGETS="broker:account_id,broker:account_id"."""
    raw = os.environ.get("RECONCILE_STARTUP_TARGETS", "")
    targets: list[tuple[str, str]] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        broker, _, account_id = item.partition(":")
        targets.append((broker.strip(), (account_id or "default").strip()))
    return targets


# --- broker client seam ------------------------------------------------------


class BrokerClientError(Exception):
    """broker-connectors could not provide positions/account state."""


class HttpBrokerClient:
    """Positions/balances from broker-connectors (the BrokerConnector seam).

    GET /connectors/{broker}/positions and GET /connectors/{broker}/account;
    409 (no connected session) and network errors surface as
    BrokerClientError so callers can distinguish "broker unavailable" from
    "no positions"."""

    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self._base_url = base_url
        self._timeout = timeout

    @property
    def base_url(self) -> str:
        return (self._base_url or broker_connectors_url()).rstrip("/")

    async def _get(self, path: str, params: dict) -> httpx.Response:
        timeout = self._timeout if self._timeout is not None else reconcile_timeout()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{self.base_url}{path}", params=params)
        except httpx.HTTPError as exc:
            raise BrokerClientError(f"broker-connectors unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise BrokerClientError(
                f"broker-connectors returned {response.status_code} for {path}: "
                f"{response.text[:300]}"
            )
        return response

    async def get_positions(self, broker: str, account_id: str) -> list[Position]:
        response = await self._get(
            f"/connectors/{broker}/positions", {"account_id": account_id}
        )
        return [Position.model_validate(item) for item in response.json()]

    async def get_account(self, broker: str, account_id: str) -> AccountState:
        response = await self._get(
            f"/connectors/{broker}/account", {"account_id": account_id}
        )
        return AccountState.model_validate(response.json())


def get_broker_client() -> HttpBrokerClient:
    """FastAPI dependency seam (overridden with fakes in tests)."""
    return HttpBrokerClient()


# --- report ------------------------------------------------------------------


def local_positions(db: Session, account_id: str) -> list[PortfolioPosition]:
    rows = db.execute(
        select(PortfolioPosition).where(PortfolioPosition.account_id == account_id)
    ).scalars()
    return [p for p in rows if p.quantity != 0]


def build_report(
    account_id: str,
    broker: str,
    broker_account_id: str,
    local: list[PortfolioPosition],
    broker_positions: list[Position],
    tolerance: float,
) -> ReconciliationReport:
    """Pure comparison of local vs broker positions per symbol.

    difference = broker_quantity - local_quantity;
    |difference| <= tolerance -> matched (fee dust);
    local == 0 -> missing_locally; broker == 0 -> missing_at_broker;
    otherwise quantity_mismatch."""
    local_by_symbol = {p.symbol: p for p in local}
    broker_by_symbol: dict[str, Position] = {}
    for position in broker_positions:
        if position.quantity != 0:
            broker_by_symbol[position.symbol] = position

    report = ReconciliationReport(
        account_id=account_id,
        broker=broker,
        broker_account_id=broker_account_id,
        tolerance=tolerance,
        generated_at=datetime.now(timezone.utc),
    )

    for symbol in sorted(set(local_by_symbol) | set(broker_by_symbol)):
        local_qty = local_by_symbol[symbol].quantity if symbol in local_by_symbol else 0.0
        broker_position = broker_by_symbol.get(symbol)
        broker_qty = broker_position.quantity if broker_position is not None else 0.0
        entry = ReconcileEntry(
            symbol=symbol,
            local_quantity=local_qty,
            broker_quantity=broker_qty,
            difference=broker_qty - local_qty,
            broker_average_price=(
                broker_position.average_price if broker_position is not None else None
            ),
        )
        if abs(entry.difference) <= tolerance:
            report.matched.append(entry)
        elif local_qty == 0.0:
            report.missing_locally.append(entry)
        elif broker_qty == 0.0:
            report.missing_at_broker.append(entry)
        else:
            report.quantity_mismatches.append(entry)

    report.discrepancies = (
        len(report.missing_locally)
        + len(report.missing_at_broker)
        + len(report.quantity_mismatches)
    )
    return report


def _discrepancy_entries(
    report: ReconciliationReport,
) -> list[tuple[str, ReconcileEntry]]:
    return (
        [("missing_locally", e) for e in report.missing_locally]
        + [("missing_at_broker", e) for e in report.missing_at_broker]
        + [("quantity_mismatch", e) for e in report.quantity_mismatches]
    )


def apply_report(
    db: Session, account_id: str, report: ReconciliationReport
) -> list[ReconciliationAdjustment]:
    """Align local positions to broker truth (broker wins).

    Each correction is recorded as a synthetic execution flagged
    source="reconciliation" with realized_pnl=0 and commission=0; account
    cash is NOT touched — this is an inventory truth adjustment, not a
    trade. Caller commits."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    adjustments: list[ReconciliationAdjustment] = []

    for kind, entry in _discrepancy_entries(report):
        position = db.execute(
            select(PortfolioPosition).where(
                PortfolioPosition.account_id == account_id,
                PortfolioPosition.symbol == entry.symbol,
            )
        ).scalar_one_or_none()

        price_used = 0.0
        if entry.broker_average_price:
            price_used = entry.broker_average_price
        elif position is not None:
            price_used = position.last_price or position.average_price

        if position is None:
            position = PortfolioPosition(
                account_id=account_id,
                symbol=entry.symbol,
                quantity=0.0,
                average_price=0.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
            )
            db.add(position)

        position.quantity = entry.broker_quantity
        if kind == "missing_locally":
            position.average_price = entry.broker_average_price or price_used
        if position.quantity == 0:
            position.average_price = 0.0
        mark = position.last_price if position.last_price is not None else price_used
        position.unrealized_pnl = position.quantity * (mark - position.average_price)

        audit = PortfolioExecution(
            account_id=account_id,
            order_id=str(uuid.uuid4()),
            client_order_id=None,
            source=RECONCILIATION_SOURCE,
            symbol=entry.symbol,
            side="buy" if entry.difference > 0 else "sell",
            status="filled",
            filled_quantity=abs(entry.difference),
            average_fill_price=price_used,
            commission=0.0,
            realized_pnl=0.0,
            raw={
                "source": RECONCILIATION_SOURCE,
                "kind": kind,
                "broker": report.broker,
                "broker_account_id": report.broker_account_id,
                "local_quantity": entry.local_quantity,
                "broker_quantity": entry.broker_quantity,
                "difference": entry.difference,
            },
            reported_at=now,
        )
        db.add(audit)
        db.flush()

        adjustments.append(
            ReconciliationAdjustment(
                symbol=entry.symbol,
                kind=kind,
                adjustment_quantity=entry.difference,
                side="buy" if entry.difference > 0 else "sell",
                price_used=price_used,
                execution_id=audit.id,
            )
        )
    return adjustments


def log_report(report: ReconciliationReport, *, context: str) -> None:
    """Loud, structured logging of every discrepancy."""
    if report.discrepancies == 0:
        logger.info(
            "reconciliation[%s] %s@%s: clean (%d matched)",
            context,
            report.account_id,
            report.broker,
            len(report.matched),
        )
        return
    logger.error(
        "reconciliation[%s] %s@%s: %d DISCREPANCIES "
        "(missing_locally=%d missing_at_broker=%d quantity_mismatches=%d)",
        context,
        report.account_id,
        report.broker,
        report.discrepancies,
        len(report.missing_locally),
        len(report.missing_at_broker),
        len(report.quantity_mismatches),
    )
    for kind, entry in _discrepancy_entries(report):
        logger.error(
            "reconciliation[%s] %s@%s %s %s: local=%s broker=%s diff=%s",
            context,
            report.account_id,
            report.broker,
            kind,
            entry.symbol,
            entry.local_quantity,
            entry.broker_quantity,
            entry.difference,
        )


# --- startup (report-only, never applies) ------------------------------------


async def run_startup_reconciliation(
    broker_client: HttpBrokerClient | None = None,
    session_factory=None,
) -> list[ReconciliationReport]:
    """Report-only reconciliation at startup for RECONCILE_STARTUP_TARGETS.

    Runs only when RECONCILE_ON_START=true. NEVER applies changes (apply is
    an explicit admin action on POST /portfolio/{account_id}/reconcile);
    discrepancies are logged loudly. Failures (broker session not connected,
    broker-connectors down) are logged and never crash startup."""
    if not reconcile_on_start():
        return []

    from app import db as db_module  # late import: tests swap SessionLocal

    client = broker_client or HttpBrokerClient()
    factory = session_factory or db_module.SessionLocal
    reports: list[ReconciliationReport] = []

    for broker, account_id in startup_targets():
        try:
            broker_positions = await client.get_positions(broker, account_id)
        except BrokerClientError as exc:
            logger.error(
                "startup reconciliation for %s@%s skipped: %s", account_id, broker, exc
            )
            continue
        with factory() as session:
            report = build_report(
                account_id,
                broker,
                account_id,
                local_positions(session, account_id),
                broker_positions,
                qty_tolerance(),
            )
            session.rollback()  # report-only: guarantee nothing is written
        log_report(report, context="startup")
        reports.append(report)
    return reports
