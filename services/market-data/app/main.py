"""market-data service (P2): shared, cached bar feed for all bots.

A single background poll per (broker, symbol, timeframe) populates a cache
(Redis when available, in-process otherwise); every bot reads bars from the
cache instead of hitting the broker directly, protecting the broker's rate
limit. On-demand reads for an un-subscribed series fetch upstream once and
cache the result.

Real websocket fan-out (pushing live ticks/bars) is a future enhancement; the
interval poller already delivers the rate-limit-protection goal and is far
more testable in this environment.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from prometheus_fastapi_instrumentator import Instrumentator

from . import config
from .cache import build_cache, cache_key
from .poller import MarketDataPoller, SubscriptionRegistry
from .schemas import BarsResponse, RefreshResult, Subscription, SubscriptionStatus
from .source import MarketDataSource, MarketDataSourceError, build_source

SERVICE_NAME = "market-data"

logger = logging.getLogger(SERVICE_NAME)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.cache = await build_cache(config.redis_url())
    app.state.source = build_source()
    app.state.registry = SubscriptionRegistry()
    app.state.poller = MarketDataPoller(
        app.state.source, app.state.cache, app.state.registry
    )
    if config.autostart_poller():
        app.state.poller.start()
    try:
        yield
    finally:
        await app.state.poller.stop()


app = FastAPI(title="market-data", version="0.1.0", lifespan=lifespan)

if not getattr(app.state, "metrics_instrumented", False):
    Instrumentator(
        should_instrument_requests_inprogress=True,
        inprogress_labels=False,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, include_in_schema=False)
    app.state.metrics_instrumented = True


# Dependency seams (overridable in tests via app.state or dependency_overrides).
def get_cache():
    return app.state.cache


def get_source() -> MarketDataSource:
    return app.state.source


def get_registry() -> SubscriptionRegistry:
    return app.state.registry


def get_poller() -> MarketDataPoller:
    return app.state.poller


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/ready")
def ready() -> dict:
    return {"status": "ready", "service": SERVICE_NAME}


@app.get("/subscriptions", response_model=list[SubscriptionStatus])
def list_subscriptions(
    registry: SubscriptionRegistry = Depends(get_registry),
) -> list[SubscriptionStatus]:
    return registry.all()


@app.post("/subscriptions", response_model=SubscriptionStatus, status_code=201)
async def add_subscription(
    body: Subscription,
    registry: SubscriptionRegistry = Depends(get_registry),
    poller: MarketDataPoller = Depends(get_poller),
) -> SubscriptionStatus:
    """Register a series so the poller keeps it warm; refresh it once now so a
    reader does not have to wait for the next poll cycle."""
    status = registry.add(body.broker, body.symbol, body.timeframe)
    await poller.refresh_one(status)
    return status


@app.delete("/subscriptions", response_model=dict)
def remove_subscription(
    body: Subscription,
    registry: SubscriptionRegistry = Depends(get_registry),
) -> dict:
    removed = registry.remove(body.broker, body.symbol, body.timeframe)
    if not removed:
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"removed": True}


@app.post("/subscriptions/refresh", response_model=RefreshResult)
async def refresh_all(poller: MarketDataPoller = Depends(get_poller)) -> RefreshResult:
    refreshed, errors = await poller.refresh_once()
    return RefreshResult(refreshed=refreshed, errors=errors)


@app.get("/market-data/{symbol}", response_model=BarsResponse)
async def get_bars(
    symbol: str,
    broker: str | None = None,
    timeframe: str = "1h",
    limit: int | None = None,
    cache=Depends(get_cache),
    source: MarketDataSource = Depends(get_source),
) -> BarsResponse:
    """Recent bars for a symbol. Served from the shared cache; on a cold miss
    the series is fetched upstream once, cached, and returned."""
    broker = broker or config.default_broker()
    key = cache_key(broker, symbol, timeframe)

    cached = await cache.get(key)
    if cached is not None:
        bars = cached[-limit:] if limit else cached
        return BarsResponse(
            broker=broker, symbol=symbol, timeframe=timeframe,
            source="cache", count=len(bars), bars=bars,
        )

    # Cold miss: always fetch the full series (max_bars) and cache it, so a
    # later request for more bars than a small first request is still served
    # from cache. Return the requested slice.
    try:
        full = await source.fetch(broker, symbol, timeframe, config.max_bars())
    except MarketDataSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await cache.set(key, full, config.cache_ttl())
    bars = full[-limit:] if limit else full
    return BarsResponse(
        broker=broker, symbol=symbol, timeframe=timeframe,
        source="upstream", count=len(bars), bars=bars,
    )
