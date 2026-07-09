"""Alembic migration 0001: fresh-create path, init.sql-preexisting path,
seed of the 9 market categories, and gateway-specific version table."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXPECTED_CODES = {
    "STOCKS", "ETFS", "FOREX", "CRYPTO", "FUTURES",
    "OPTIONS", "COMMODITIES", "BONDS", "INDICES",
}


def _upgrade_head(db_url: str) -> None:
    config = Config(os.path.join(SERVICE_DIR, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(SERVICE_DIR, "alembic"))
    old_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    try:
        command.upgrade(config, "head")
    finally:
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url


@pytest.fixture()
def sqlite_url(tmp_path):
    return f"sqlite:///{tmp_path / 'migration.db'}"


def test_migration_on_fresh_database(sqlite_url) -> None:
    _upgrade_head(sqlite_url)

    engine = sa.create_engine(sqlite_url)
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        assert inspector.has_table("markets")
        assert inspector.has_table("symbols")
        assert inspector.has_table("user_market_settings")
        # gateway keeps its own alembic version table (no collision with
        # other services migrating the same database)
        assert inspector.has_table("alembic_version_gateway")
        assert not inspector.has_table("alembic_version")

        codes = set(conn.execute(sa.text("SELECT code FROM markets")).scalars())
        assert codes == EXPECTED_CODES
        enabled = list(conn.execute(sa.text("SELECT enabled FROM markets")).scalars())
        assert len(enabled) == 9 and all(bool(flag) for flag in enabled)
    engine.dispose()


def test_migration_extends_init_sql_stub_tables(sqlite_url) -> None:
    """init.sql may have created stub markets/symbols already; the migration
    must ALTER them (adding Fase 4 columns) and still seed the 9 markets."""
    engine = sa.create_engine(sqlite_url)
    with engine.begin() as conn:
        conn.execute(
            sa.text("CREATE TABLE markets (id VARCHAR(36) PRIMARY KEY, name VARCHAR(100) UNIQUE NOT NULL)")
        )
        conn.execute(
            sa.text(
                "CREATE TABLE symbols (id VARCHAR(36) PRIMARY KEY,"
                " market_id VARCHAR(36) NOT NULL REFERENCES markets(id),"
                " ticker VARCHAR(50) NOT NULL, UNIQUE (market_id, ticker))"
            )
        )
        # a pre-existing market row must survive and be backfilled, not duplicated
        conn.execute(sa.text("INSERT INTO markets (id, name) VALUES ('m-legacy', 'Crypto')"))
    engine.dispose()

    _upgrade_head(sqlite_url)

    engine = sa.create_engine(sqlite_url)
    with engine.connect() as conn:
        inspector = sa.inspect(conn)
        market_cols = {col["name"] for col in inspector.get_columns("markets")}
        assert {"code", "asset_class", "enabled", "trading_hours"} <= market_cols
        symbol_cols = {col["name"] for col in inspector.get_columns("symbols")}
        assert {"name", "is_active", "created_at"} <= symbol_cols

        rows = conn.execute(sa.text("SELECT id, name, code FROM markets")).all()
        assert len(rows) == 9  # legacy 'Crypto' kept, 8 seeded, no duplicate
        legacy = next(row for row in rows if row.id == "m-legacy")
        assert legacy.code == "CRYPTO"  # backfilled from name
    engine.dispose()
