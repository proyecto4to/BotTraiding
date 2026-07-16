"""Shared pytest fixtures: an in-memory SQLite DB wired into app.db (same
pattern as auth-service) plus JWT helpers and a generous default rate limiter
so unrelated tests never trip throttling."""

from __future__ import annotations

import os
import time

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite://")
# The suite must exercise the in-memory limiter deterministically; per-test
# Redis limiters are built explicitly in test_rate_limit.py.
os.environ.pop("REDIS_URL", None)
os.environ.pop("RATE_LIMIT_BACKEND", None)

import pytest
from app import db as db_module
from app import rate_limit
from app.models import Base, Market, Symbol
from app.seed_data import MARKET_SEED
from jose import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

JWT_SECRET = "test-secret"
ALGORITHM = "HS256"


def make_token(
    sub: str = "user-1",
    roles: list[str] | None = None,
    token_type: str = "access",
    mfa_pending: bool = False,
    expired: bool = False,
) -> str:
    payload = {
        "sub": sub,
        "roles": roles if roles is not None else ["viewer"],
        "type": token_type,
        "mfa_pending": mfa_pending,
        "exp": int(time.time()) + (-3600 if expired else 3600),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def auth_headers(**kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(**kwargs)}"}


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
def _generous_rate_limiter():
    """Default limiter big enough that ordinary tests never hit 429."""
    rate_limit.set_rate_limiter(
        rate_limit.TokenBucketRateLimiter(capacity=10_000, refill_per_second=10_000)
    )
    yield
    rate_limit.set_rate_limiter(None)


@pytest.fixture()
def db_session():
    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def seeded_markets(db_session):
    """Insert the canonical 9 market categories; returns {code: Market}."""
    markets = [
        Market(
            name=item["name"],
            code=item["code"],
            asset_class=item["asset_class"],
            enabled=True,
            trading_hours=item["trading_hours"],
        )
        for item in MARKET_SEED
    ]
    db_session.add_all(markets)
    db_session.commit()
    for market in markets:
        db_session.refresh(market)
    return {market.code: market for market in markets}


@pytest.fixture()
def seeded_symbols(db_session, seeded_markets):
    """A couple of symbols in the Crypto and Stocks markets."""
    symbols = [
        Symbol(market_id=seeded_markets["CRYPTO"].id, ticker="BTCUSDT", name="Bitcoin/USDT"),
        Symbol(market_id=seeded_markets["CRYPTO"].id, ticker="ETHUSDT", name="Ether/USDT"),
        Symbol(market_id=seeded_markets["STOCKS"].id, ticker="AAPL", name="Apple Inc."),
    ]
    db_session.add_all(symbols)
    db_session.commit()
    for symbol in symbols:
        db_session.refresh(symbol)
    return symbols


@pytest.fixture()
def client():
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)
