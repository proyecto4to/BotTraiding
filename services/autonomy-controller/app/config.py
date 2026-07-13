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


# Bots the controller manages carry this name prefix so it only ever
# creates/stops its own bots, never a human-created one.
BOT_NAME_PREFIX = "auto:"
