"""Fase 4 gateway schema: markets, symbols, user_market_settings + seed.

infra/docker/init.sql may already have created stub `markets` (id, name) and
`symbols` (id, market_id, ticker) tables on a fresh Postgres, so this
migration is written to handle both cases:

- table missing  -> create it with the full Fase 4 column set
- table present  -> ALTER it to add the missing Fase 4 columns

It then seeds the 9 market categories (stocks, ETFs, forex, crypto, futures,
options, commodities, bonds, indices) from app.seed_data, inserting only the
ones whose `name` is not already present (idempotent).

`user_market_settings.user_id` deliberately has no FK to `users`: that table
is owned by auth-service and each service migrates independently (own
alembic version table), so migration order must not matter.

Revision ID: 0001
Revises:
Create Date: 2026-07-09
"""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.seed_data import MARKET_SEED

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _is_postgres(bind) -> bool:
    return bind.dialect.name == "postgresql"


def _uuid_type(bind):
    return postgresql.UUID(as_uuid=False) if _is_postgres(bind) else sa.String(36)


def _json_type(bind):
    return postgresql.JSONB if _is_postgres(bind) else sa.JSON


def _uuid_default(bind):
    return sa.text("uuid_generate_v4()") if _is_postgres(bind) else None


def _column_names(inspector, table: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table)}


def _added_timestamp_column(bind, name: str) -> sa.Column:
    """Timestamp column for ALTER TABLE ADD COLUMN. SQLite (migration test
    only) cannot add a NOT NULL column with a non-constant default, so it
    gets a nullable column instead; Postgres gets the real definition."""
    if _is_postgres(bind):
        return sa.Column(
            name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        )
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    bind = op.get_bind()
    if _is_postgres(bind):
        op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    inspector = sa.inspect(bind)
    json_default = sa.text("'{}'::jsonb") if _is_postgres(bind) else sa.text("'{}'")

    # -- markets ---------------------------------------------------------
    if not inspector.has_table("markets"):
        op.create_table(
            "markets",
            sa.Column(
                "id",
                _uuid_type(bind),
                primary_key=True,
                server_default=_uuid_default(bind),
            ),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column("code", sa.String(20), nullable=False, unique=True),
            sa.Column("asset_class", sa.String(50), nullable=False),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("trading_hours", _json_type(bind), nullable=False, server_default=json_default),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    else:
        existing = _column_names(inspector, "markets")
        # code/asset_class: add nullable, backfill any pre-existing rows,
        # then tighten to NOT NULL so old and new deployments converge.
        # (NOT NULL/UNIQUE tightening is Postgres-only: SQLite - used by the
        # migration test - does not support ALTER COLUMN / ADD CONSTRAINT.)
        if "code" not in existing:
            op.add_column("markets", sa.Column("code", sa.String(20), nullable=True))
            op.execute(
                "UPDATE markets SET code = upper(substr(name, 1, 20)) WHERE code IS NULL"
            )
            if _is_postgres(bind):
                op.alter_column("markets", "code", nullable=False)
                op.create_unique_constraint("uq_markets_code", "markets", ["code"])
        if "asset_class" not in existing:
            op.add_column("markets", sa.Column("asset_class", sa.String(50), nullable=True))
            op.execute("UPDATE markets SET asset_class = 'unknown' WHERE asset_class IS NULL")
            if _is_postgres(bind):
                op.alter_column("markets", "asset_class", nullable=False)
        if "enabled" not in existing:
            op.add_column(
                "markets",
                sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            )
        if "trading_hours" not in existing:
            op.add_column(
                "markets",
                sa.Column("trading_hours", _json_type(bind), nullable=False, server_default=json_default),
            )
        if "created_at" not in existing:
            op.add_column("markets", _added_timestamp_column(bind, "created_at"))
        if "updated_at" not in existing:
            op.add_column("markets", _added_timestamp_column(bind, "updated_at"))

    # -- symbols ---------------------------------------------------------
    if not inspector.has_table("symbols"):
        op.create_table(
            "symbols",
            sa.Column(
                "id",
                _uuid_type(bind),
                primary_key=True,
                server_default=_uuid_default(bind),
            ),
            sa.Column(
                "market_id",
                _uuid_type(bind),
                sa.ForeignKey("markets.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("ticker", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("market_id", "ticker", name="uq_symbols_market_ticker"),
        )
        op.create_index("ix_symbols_market_id", "symbols", ["market_id"])
    else:
        existing = _column_names(inspector, "symbols")
        if "name" not in existing:
            op.add_column("symbols", sa.Column("name", sa.String(255), nullable=True))
        if "is_active" not in existing:
            op.add_column(
                "symbols",
                sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            )
        if "created_at" not in existing:
            op.add_column("symbols", _added_timestamp_column(bind, "created_at"))

    # -- user_market_settings (gateway-owned, always new) ------------------
    if not inspector.has_table("user_market_settings"):
        op.create_table(
            "user_market_settings",
            sa.Column("user_id", _uuid_type(bind), primary_key=True),
            sa.Column(
                "market_id",
                _uuid_type(bind),
                sa.ForeignKey("markets.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    # -- seed the 9 market categories (insert only what is missing) --------
    existing_names = set(bind.execute(sa.text("SELECT name FROM markets")).scalars())
    markets_table = sa.table(
        "markets",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("code", sa.String),
        sa.column("asset_class", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("trading_hours", sa.JSON),
    )
    rows = [
        {
            "id": str(uuid.uuid4()),
            "name": market["name"],
            "code": market["code"],
            "asset_class": market["asset_class"],
            "enabled": True,
            "trading_hours": market["trading_hours"],
        }
        for market in MARKET_SEED
        if market["name"] not in existing_names
    ]
    if rows:
        op.bulk_insert(markets_table, rows)


def downgrade() -> None:
    op.drop_table("user_market_settings")
    op.drop_table("symbols")
    op.drop_table("markets")
