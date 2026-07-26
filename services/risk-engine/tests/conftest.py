"""Shared fixtures: in-memory SQLite wired into app.db (auth-service
pattern), test JWTs, and portfolio-state / signal builders."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.pop("NATS_URL", None)  # events fall back to logging in tests

import pytest
from jose import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db as db_module
from app.models import Base
from app.schemas import DrawdownIn, ExposureIn, PortfolioStateIn
from trading_contracts import AccountState, Position


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


@pytest.fixture()
def db_session():
    with db_module.SessionLocal() as session:
        yield session


@pytest.fixture()
def client():
    """Speaks as trading-engine does: /risk/validate rejects unauthenticated
    callers. `anon_client` covers the rejection itself."""
    from fastapi.testclient import TestClient

    from app.main import app
    from trading_contracts.auth import service_auth_header

    return TestClient(app, headers=service_auth_header("trading-engine"))


@pytest.fixture()
def anon_client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def make_token(roles: list[str], token_type: str = "access") -> str:
    payload = {
        "sub": str(uuid.uuid4()),
        "roles": roles,
        "type": token_type,
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


@pytest.fixture()
def admin_headers():
    return {"Authorization": f"Bearer {make_token(['admin'])}"}


@pytest.fixture()
def trader_headers():
    return {"Authorization": f"Bearer {make_token(['trader'])}"}


def make_state(
    equity: float = 100_000.0,
    cash: float | None = None,
    positions: list[Position] | None = None,
    marks: dict[str, float] | None = None,
    returns: dict[str, list[float]] | None = None,
    gross_exposure: float = 0.0,
    per_symbol: dict[str, float] | None = None,
    per_sector: dict[str, float] | None = None,
    pnl_daily: float = 0.0,
    pnl_weekly: float = 0.0,
    pnl_monthly: float = 0.0,
    current_drawdown: float = 0.0,
    floating_drawdown: float = 0.0,
    free_margin: float | None = None,
    account_id: str = "acc-1",
) -> PortfolioStateIn:
    return PortfolioStateIn(
        account=AccountState(
            account_id=account_id,
            balance=cash if cash is not None else equity,
            equity=equity,
            margin_used=gross_exposure,
            free_margin=free_margin if free_margin is not None else equity - gross_exposure,
        ),
        positions=positions or [],
        marks=marks or {},
        returns=returns or {},
        exposure=ExposureIn(
            gross_exposure=gross_exposure,
            net_exposure=gross_exposure,
            per_symbol=per_symbol or {},
            per_sector=per_sector or {},
        ),
        drawdown=DrawdownIn(
            equity=equity,
            peak_equity=equity,
            current_drawdown=current_drawdown,
            floating_drawdown=floating_drawdown,
        ),
        pnl_daily=pnl_daily,
        pnl_weekly=pnl_weekly,
        pnl_monthly=pnl_monthly,
    )


def make_signal(
    symbol: str = "AAPL",
    side: str = "buy",
    suggested_size: float = 100.0,
    stop_loss: float | None = 95.0,
    price: float | None = 100.0,
    metadata: dict | None = None,
):
    from trading_contracts import OrderSide, TradeSignal

    meta = dict(metadata or {})
    if price is not None and "price" not in meta:
        meta["price"] = price
    return TradeSignal(
        id=uuid.uuid4(),
        strategy_id="strat-1",
        symbol=symbol,
        market="stocks",
        side=OrderSide(side),
        confidence=0.9,
        timeframe="1h",
        suggested_size=suggested_size,
        stop_loss=stop_loss,
        take_profit=None,
        generated_at=datetime.now(timezone.utc),
        metadata=meta,
    )
