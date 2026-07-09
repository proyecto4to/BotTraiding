"""initial strategy-engine schema

Reproduces infra/docker/init.sql's strategies/strategy_versions/
strategy_configs tables extended with the Fase 6 catalogue columns
(strategy_key, description, markets, timeframes, enabled, updated_at).
init.sql itself is never edited (owned by infra); this migration is the
strategy-engine-owned source of truth, applied by docker-entrypoint.sh
with version_table "alembic_version_strategy".

Ownership deviation from init.sql: user_id/account_id are plain UUID
columns WITHOUT cross-service foreign keys - users belongs to
auth-service and broker_accounts to broker-connectors, and services never
depend on each other's tables (docs/ARCHITECTURE.md, principle 1). This
also removes any startup ordering requirement between services.

Revision ID: 0001
Revises:
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        "strategies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("strategy_key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "markets", postgresql.JSONB, nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "timeframes", postgresql.JSONB, nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )

    op.create_table(
        "strategy_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "strategy_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("strategies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column(
            "parameters", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("strategy_id", "version", name="uq_strategy_version"),
    )

    op.create_table(
        "strategy_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "strategy_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("strategy_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "overrides", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_strategy_configs_user", "strategy_configs", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_configs_user", table_name="strategy_configs")
    op.drop_table("strategy_configs")
    op.drop_table("strategy_versions")
    op.drop_table("strategies")
