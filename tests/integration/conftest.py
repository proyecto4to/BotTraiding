"""Integration-suite fixtures: the REAL service apps, in-process, wired.

The hard part solved here: every service ships a top-level package named
``app`` that imports itself absolutely (``from app import db``), so the
apps cannot be imported side by side naively. ``_load_service`` temporarily
owns the ``app`` name (sys.path + sys.modules), imports the service's
``app.main`` (which pulls in the whole package), then re-registers every
loaded module under a unique ``<alias>_app.*`` name and restores whatever
``app`` meant before. The loaded modules keep working afterwards because
their globals hold direct object references; no service does a lazy
``import app.x`` at request time.

Isolation and wiring:
- each service gets its own StaticPool in-memory SQLite engine per test
  (the same override every service's own conftest performs);
- inter-service HTTP is replaced by httpx.ASGITransport clients, so the
  real endpoint code runs in-process:
    trading-engine  -> strategy-engine / risk-engine / execution-engine
    risk-engine     -> portfolio-engine   (portfolio_client override)
    execution-engine-> paper-trading      (router transport override)
    execution-engine-> portfolio-engine   (forwarder override)
- market data is synthetic (broker-connectors is out of scope here): the
  MarketDataClient seam receives crafted bar series.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# --- environment BEFORE any service import ----------------------------------
os.environ["DATABASE_URL"] = "sqlite://"  # engines are rebuilt per test anyway
os.environ.setdefault("JWT_SECRET", "integration-secret")
os.environ.pop("NATS_URL", None)  # all event seams fall back to logging
os.environ.pop("EXECUTION_MODE", None)  # default mode: paper

# Neutralize Prometheus instrumentation: six apps in one process would
# register duplicate collectors in the global registry. Metrics are not
# under test here.
from prometheus_fastapi_instrumentator import Instrumentator  # noqa: E402

Instrumentator.instrument = lambda self, app, **kwargs: self  # type: ignore[method-assign]
Instrumentator.expose = lambda self, app, **kwargs: self  # type: ignore[method-assign]

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_DIR = REPO_ROOT / "services"

SERVICE_ALIASES = {
    "strategy": "strategy-engine",
    "risk": "risk-engine",
    "portfolio": "portfolio-engine",
    "execution": "execution-engine",
    "paper": "paper-trading",
    "trading": "trading-engine",
}


class LoadedService(SimpleNamespace):
    """One imported service: .app (FastAPI), .get('db') -> app.db module."""

    def get(self, name: str = ""):
        key = "app" if not name else f"app.{name}"
        return self.modules[key]


def _load_service(alias: str, service_name: str) -> LoadedService:
    service_dir = SERVICES_DIR / service_name
    assert service_dir.is_dir(), f"missing service directory {service_dir}"

    saved = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, str(service_dir))
    importlib.invalidate_caches()
    try:
        main = importlib.import_module("app.main")
        loaded = {
            k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")
        }
        # keep the modules importable/debuggable under a unique alias
        for k, v in loaded.items():
            sys.modules[k.replace("app", f"{alias}_service_app", 1)] = v
    finally:
        sys.path.remove(str(service_dir))
        for k in list(sys.modules):
            if k == "app" or k.startswith("app."):
                del sys.modules[k]
        sys.modules.update(saved)

    return LoadedService(
        alias=alias, name=service_name, dir=service_dir, modules=loaded, app=main.app
    )


@pytest.fixture(scope="session")
def services() -> dict[str, LoadedService]:
    """All six real apps, loaded once per test session."""
    return {alias: _load_service(alias, name) for alias, name in SERVICE_ALIASES.items()}


# --- per-test isolated SQLite DBs ---------------------------------------------


def _fresh_sqlite(svc: LoadedService) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    db_module = svc.get("db")
    models = svc.get("models")
    models.Base.metadata.create_all(engine)
    db_module.engine = engine
    db_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )


@pytest.fixture(autouse=True)
def _isolated_dbs(services):
    for svc in services.values():
        _fresh_sqlite(svc)

    # portfolio-engine keeps process-local marks/returns: reset per test
    services["portfolio"].get("portfolio").reset_memory_state()

    # strategy-engine startup sync (normally done by its lifespan)
    strategy = services["strategy"]
    with strategy.get("db").SessionLocal() as session:
        strategy.get("sync").sync_registry(session, strategy.get("registry").registry)

    yield

    services["portfolio"].get("portfolio").reset_memory_state()
    for svc in services.values():
        svc.app.dependency_overrides.clear()


# --- in-process transports ------------------------------------------------------


def asgi_client(app: Any, name: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"http://{name}"
    )


class InProcessPortfolioClient:
    """risk-engine's PortfolioClient contract against the in-process
    portfolio-engine app."""

    def __init__(self, portfolio_app: Any, risk_schemas: Any) -> None:
        self._client = asgi_client(portfolio_app, "portfolio-engine")
        self._state_model = risk_schemas.PortfolioStateIn

    async def get_state(self, account_id: str):
        response = await self._client.get(f"/portfolio/{account_id}")
        response.raise_for_status()
        return self._state_model.model_validate(response.json())


class InProcessPaperTransport:
    """execution-engine ExecutionTransport protocol -> paper-trading app."""

    def __init__(self, paper_app: Any, retry_module: Any) -> None:
        from trading_contracts import ExecutionMode, ExecutionReport

        self.mode = ExecutionMode.PAPER
        self.name = "paper-trading-inprocess"
        self._report_model = ExecutionReport
        self._retry = retry_module
        self._client = asgi_client(paper_app, "paper-trading")

    async def place_order(self, order, market_price):
        price = market_price if market_price is not None else order.price
        if price is None:
            raise self._retry.PermanentTransportError("paper execution requires a price")
        payload = {
            "order_id": str(order.id),
            "signal_id": str(order.signal_id),
            "account_id": order.account_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
            "order_type": order.order_type.value,
            "price": price,
        }
        response = await self._client.post("/paper/orders", json=payload)
        if response.status_code >= 400:
            raise self._retry.PermanentTransportError(
                f"paper-trading returned {response.status_code}: {response.text[:300]}"
            )
        return self._report_model.model_validate(response.json())

    async def cancel_order(self, order_id, *, broker, account_id):
        response = await self._client.post(f"/paper/orders/{order_id}/cancel", json={})
        return response.status_code < 400


class InProcessForwarder:
    """execution-engine PortfolioForwarder contract -> portfolio-engine app."""

    def __init__(self, portfolio_app: Any) -> None:
        self._client = asgi_client(portfolio_app, "portfolio-engine")

    async def forward(self, account_id: str, payload: dict) -> bool:
        response = await self._client.post(
            f"/portfolio/{account_id}/executions", json=payload
        )
        return response.status_code < 400


class SyntheticMarketData:
    """trading-engine MarketDataClient seam fed with crafted bar series
    (broker-connectors is exercised by its own suite, not here)."""

    def __init__(self, bars_by_symbol: dict[str, list[dict]]) -> None:
        self.bars_by_symbol = bars_by_symbol

    async def get_bars(self, broker, symbol, timeframe, lookback=None, account_id="default"):
        return self.bars_by_symbol.get(symbol, [])


# --- the fully wired platform -----------------------------------------------------


class Platform(SimpleNamespace):
    """Everything a test needs: loaded services + wired trading clients +
    direct ASGI clients for assertions."""

    def run(self, coro):
        return asyncio.run(coro)

    def get_json(self, client: httpx.AsyncClient, path: str, **kwargs) -> Any:
        async def _get():
            response = await client.get(path, **kwargs)
            assert response.status_code < 400, f"GET {path} -> {response.status_code}: {response.text[:300]}"
            return response.json()

        return self.run(_get())

    def post_json(self, client: httpx.AsyncClient, path: str, json: dict, **kwargs) -> Any:
        async def _post():
            response = await client.post(path, json=json, **kwargs)
            assert response.status_code < 400, f"POST {path} -> {response.status_code}: {response.text[:300]}"
            return response.json()

        return self.run(_post())


def build_clients(services, bars_by_symbol: dict[str, list[dict]]):
    """trading-engine's real client classes over ASGI transports."""
    tclients = services["trading"].get("clients")
    return tclients.Clients(
        market_data=SyntheticMarketData(bars_by_symbol),
        strategy=tclients.StrategyClient(
            http=asgi_client(services["strategy"].app, "strategy-engine")
        ),
        risk=tclients.RiskClient(http=asgi_client(services["risk"].app, "risk-engine")),
        execution=tclients.ExecutionClient(
            http=asgi_client(services["execution"].app, "execution-engine")
        ),
    )


@pytest.fixture()
def platform(services) -> Platform:
    strategy = services["strategy"]
    risk = services["risk"]
    portfolio = services["portfolio"]
    execution = services["execution"]
    paper = services["paper"]
    trading = services["trading"]

    # risk-engine -> portfolio-engine
    risk_pc = risk.get("portfolio_client")
    risk.app.dependency_overrides[risk_pc.get_portfolio_client] = (
        lambda: InProcessPortfolioClient(portfolio.app, risk.get("schemas"))
    )

    # execution-engine -> paper-trading + portfolio-engine
    exec_router = execution.get("router")
    exec_retry = execution.get("retry")
    exec_pc = execution.get("portfolio_client")
    from trading_contracts import ExecutionMode

    async def _no_sleep(_delay: float) -> None:
        return None

    execution.app.dependency_overrides[exec_router.get_router] = (
        lambda: exec_router.ExecutionRouter(
            {ExecutionMode.PAPER: InProcessPaperTransport(paper.app, exec_retry)},
            max_attempts=2,
            base_delay=0.0,
            max_delay=0.0,
            jitter=0.0,
            sleep=_no_sleep,
        )
    )
    execution.app.dependency_overrides[exec_pc.get_portfolio_forwarder] = (
        lambda: InProcessForwarder(portfolio.app)
    )

    bars_by_symbol: dict[str, list[dict]] = {}
    clients = build_clients(services, bars_by_symbol)

    # trading-engine run-once and BotRunner both consume this bundle
    tclients = trading.get("clients")
    trading.app.dependency_overrides[tclients.get_clients] = lambda: clients

    return Platform(
        services=services,
        clients=clients,
        bars_by_symbol=bars_by_symbol,
        strategy_http=asgi_client(strategy.app, "strategy-engine"),
        risk_http=asgi_client(risk.app, "risk-engine"),
        portfolio_http=asgi_client(portfolio.app, "portfolio-engine"),
        execution_http=asgi_client(execution.app, "execution-engine"),
        paper_http=asgi_client(paper.app, "paper-trading"),
        trading=trading,
    )


# --- market data + auth helpers ------------------------------------------------


def bars_from_closes(
    closes: list[float], symbol: str = "BTCUSD", timeframe: str = "1h"
) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "open": close,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0,
            "timestamp": (start + timedelta(hours=i)).isoformat(),
        }
        for i, close in enumerate(closes)
    ]


def synthetic_uptrend_bars(symbol: str = "BTCUSD", timeframe: str = "1h") -> list[dict]:
    """A decline followed by a rally, extended bar-by-bar until the REAL
    sma_crossover plugin fires on the LAST bar (crossovers only trigger on
    the final bar, so stopping at the first signal guarantees that)."""
    from trading_strategies.builtins.trend import SmaCrossover

    plugin = SmaCrossover({})
    closes = [100.0 - 0.2 * i for i in range(40)]
    for _ in range(60):
        closes.append(closes[-1] + 1.5)
        bars = bars_from_closes(closes, symbol=symbol, timeframe=timeframe)
        if plugin.evaluate(bars) is not None:
            return bars
    raise AssertionError("synthetic series never triggered sma_crossover")


def make_token(roles: list[str], sub: str = "integration-user") -> str:
    from jose import jwt

    payload = {
        "sub": sub,
        "roles": roles,
        "type": "access",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")


def auth_headers(roles: list[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(roles)}"}
