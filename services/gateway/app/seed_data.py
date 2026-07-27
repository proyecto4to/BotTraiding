"""Canonical seed data for the 9 Fase 4 market categories.

Single source of truth used by the Alembic migration (0001) to seed the
`markets` table and by the test suite to build fixture data. trading_hours
values are placeholders: real session calendars (holidays, half-days,
exchange-specific hours) are future work and live in DB, not code.
"""

from __future__ import annotations

_US_EQUITY_HOURS = {
    "timezone": "America/New_York",
    "sessions": [
        {"days": ["mon", "tue", "wed", "thu", "fri"], "open": "09:30", "close": "16:00"}
    ],
}

_TWENTY_FOUR_FIVE_HOURS = {
    "timezone": "UTC",
    "sessions": [
        {"days": ["mon", "tue", "wed", "thu", "fri"], "open": "00:00", "close": "24:00"}
    ],
}

_TWENTY_FOUR_SEVEN_HOURS = {
    "timezone": "UTC",
    "sessions": [
        {
            "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "open": "00:00",
            "close": "24:00",
        }
    ],
}

MARKET_SEED: list[dict] = [
    {"name": "Stocks", "code": "STOCKS", "asset_class": "equity", "trading_hours": _US_EQUITY_HOURS},
    {"name": "ETFs", "code": "ETFS", "asset_class": "etf", "trading_hours": _US_EQUITY_HOURS},
    {"name": "Forex", "code": "FOREX", "asset_class": "forex", "trading_hours": _TWENTY_FOUR_FIVE_HOURS},
    {"name": "Crypto", "code": "CRYPTO", "asset_class": "crypto", "trading_hours": _TWENTY_FOUR_SEVEN_HOURS},
    {"name": "Futures", "code": "FUTURES", "asset_class": "futures", "trading_hours": _TWENTY_FOUR_FIVE_HOURS},
    {"name": "Options", "code": "OPTIONS", "asset_class": "options", "trading_hours": _US_EQUITY_HOURS},
    {"name": "Commodities", "code": "COMMODITIES", "asset_class": "commodity", "trading_hours": _TWENTY_FOUR_FIVE_HOURS},
    {"name": "Bonds", "code": "BONDS", "asset_class": "bond", "trading_hours": _US_EQUITY_HOURS},
    {"name": "Indices", "code": "INDICES", "asset_class": "index", "trading_hours": _US_EQUITY_HOURS},
]


def seed_markets(db) -> int:
    """Insert any missing market rows. Returns how many were added.

    The Alembic migration (0001) seeds these against Postgres, but the local
    Windows start-up path creates tables with `create_all` instead — the
    migrations use Postgres-specific types — so without this the `markets`
    table stays empty and the dashboard's Markets page reports "no markets
    configured". Matching on `name` (unique) makes it safe to run on every
    boot; existing rows, including any an admin disabled, are left untouched.
    """
    from app.models import Market

    existing = {name for (name,) in db.query(Market.name).all()}
    added = 0
    for market in MARKET_SEED:
        if market["name"] in existing:
            continue
        db.add(
            Market(
                name=market["name"],
                code=market["code"],
                asset_class=market["asset_class"],
                enabled=True,
                trading_hours=market["trading_hours"],
            )
        )
        added += 1
    if added:
        db.commit()
    return added
