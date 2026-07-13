"""Runtime configuration for autonomy-controller (P4).

The controller is the brain that runs the platform hands-off: on each tick it
asks the AI for the market regime and the best strategies, then creates/starts/
stops paper bots on trading-engine to match — all under the risk controls the
downstream services already enforce. Values are read at call time so tests
monkeypatch per case.
"""

from __future__ import annotations

import os


def _csv(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# --- downstream services -----------------------------------------------------
def ai_engine_url() -> str:
    return os.environ.get("AI_ENGINE_URL", "http://ai-engine:8000").rstrip("/")


def market_data_url() -> str:
    return os.environ.get("MARKET_DATA_URL", "http://market-data:8000").rstrip("/")


def trading_engine_url() -> str:
    return os.environ.get("TRADING_ENGINE_URL", "http://trading-engine:8000").rstrip("/")


def portfolio_engine_url() -> str:
    return os.environ.get("PORTFOLIO_ENGINE_URL", "http://portfolio-engine:8000").rstrip("/")


def http_timeout() -> float:
    return float(os.environ.get("AUTONOMY_HTTP_TIMEOUT", "10"))


# --- service identity (mints a JWT to call trading-engine) -------------------
def jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "dev-insecure-secret-change-me")


def system_user_id() -> str:
    return os.environ.get(
        "AUTONOMY_SYSTEM_USER_ID", "00000000-0000-0000-0000-0000000000a1"
    )


# --- trading universe & risk budget -----------------------------------------
def symbols() -> list[str]:
    return _csv("AUTONOMY_SYMBOLS", "BTCUSDT")


def timeframe() -> str:
    return os.environ.get("AUTONOMY_TIMEFRAME", "1h")


def market() -> str:
    return os.environ.get("AUTONOMY_MARKET", "crypto")


def broker() -> str:
    return os.environ.get("AUTONOMY_BROKER", "binance")


def account_id() -> str:
    return os.environ.get("AUTONOMY_ACCOUNT_ID", "autonomy")


def top_n_per_symbol() -> int:
    return int(os.environ.get("AUTONOMY_TOP_N", "1"))


def max_active_bots() -> int:
    return int(os.environ.get("AUTONOMY_MAX_ACTIVE_BOTS", "5"))


def bar_limit() -> int:
    return int(os.environ.get("AUTONOMY_BAR_LIMIT", "200"))


def bot_cycle_interval() -> int:
    return int(os.environ.get("AUTONOMY_CYCLE_INTERVAL_SECONDS", "60"))


# --- global risk guard (P9): platform-level circuit breaker ------------------
def max_drawdown() -> float:
    """Halt automation if aggregate drawdown reaches this fraction (0 disables).
    Default 25%."""
    return float(os.environ.get("AUTONOMY_MAX_DRAWDOWN", "0.25"))


def max_daily_loss_fraction() -> float:
    """Halt if the day's loss reaches this fraction of equity (0 disables).
    Off by default: absolute tolerance depends on the account, so it is opt-in."""
    return float(os.environ.get("AUTONOMY_MAX_DAILY_LOSS", "0"))


# --- capital allocation (P7) -------------------------------------------------
def deployable_fraction() -> float:
    """Fraction of the account budget the automation may deploy across all
    selected strategies (the rest stays as a reserve). Default 100%."""
    return float(os.environ.get("AUTONOMY_DEPLOYABLE_FRACTION", "1.0"))


def base_risk_per_trade() -> float:
    """Total per-trade risk budget (fraction of equity) distributed across the
    selected strategies by AI weight. Default 1%."""
    return float(os.environ.get("AUTONOMY_BASE_RISK_PER_TRADE", "0.01"))


def max_exposure_per_symbol() -> float:
    """Cap on any single (symbol, strategy) capital share. Default 50%."""
    return float(os.environ.get("AUTONOMY_MAX_EXPOSURE_PER_SYMBOL", "0.5"))


def rebalance_threshold() -> float:
    """Relative change in a bot's risk_per_trade that triggers a rebalance
    (stop -> patch -> start). Default 10%; avoids churn on tiny weight drift."""
    return float(os.environ.get("AUTONOMY_REBALANCE_THRESHOLD", "0.1"))


# --- paper -> live promotion gates (P18) -------------------------------------
def min_paper_days() -> float:
    """Minimum paper-trading track record before live is allowed. Default 14."""
    return float(os.environ.get("AUTONOMY_MIN_PAPER_DAYS", "14"))


def max_promote_drawdown() -> float:
    """Max observed drawdown that still allows promotion. Default 20%."""
    return float(os.environ.get("AUTONOMY_MAX_PROMOTE_DRAWDOWN", "0.20"))


def min_paper_return() -> float:
    """Minimum total paper return to promote (default 0 = at least break-even)."""
    return float(os.environ.get("AUTONOMY_MIN_PAPER_RETURN", "0.0"))


def min_sharpe() -> float | None:
    """Optional minimum Sharpe gate (unset/empty disables it)."""
    raw = os.environ.get("AUTONOMY_MIN_SHARPE", "").strip()
    return float(raw) if raw else None


def backtest_coherence_tolerance() -> float | None:
    """Optional paper-vs-backtest coherence gate (unset/empty disables it)."""
    raw = os.environ.get("AUTONOMY_BACKTEST_COHERENCE", "").strip()
    return float(raw) if raw else None


# Bots the controller manages carry this name prefix so it only ever
# creates/stops its own bots, never a human-created one.
BOT_NAME_PREFIX = "auto:"
