"""initial trading-engine schema

trading_bots (bot registry: pure configuration + status) and
trading_cycle_reports (per-cycle audit trail of signals/decisions/orders/
errors). Uses version_table="alembic_version_trading" so multiple services
can share one Postgres database (see alembic/env.py).

Revision ID: 0001
Revises:
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trading_bots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("broker", sa.String(50), nullable=False),
        sa.Column(
            "execution_mode", sa.String(10), nullable=False, server_default="paper"
        ),
        sa.Column("symbols", sa.JSON, nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("strategy_keys", sa.JSON, nullable=False),
        sa.Column("params_overrides", sa.JSON, nullable=False),
        sa.Column(
            "cycle_interval_seconds", sa.Float, nullable=False, server_default="60"
        ),
        sa.Column("status", sa.String(10), nullable=False, server_default="stopped"),
        sa.Column("status_reason", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_trading_bots_account_id", "trading_bots", ["account_id"])
    op.create_index("ix_trading_bots_status", "trading_bots", ["status"])

    op.create_table(
        "trading_cycle_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "bot_id",
            sa.String(36),
            sa.ForeignKey("trading_bots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("finished_at", sa.DateTime, nullable=False),
        sa.Column("signals", sa.JSON, nullable=False),
        sa.Column("decisions", sa.JSON, nullable=False),
        sa.Column("orders", sa.JSON, nullable=False),
        sa.Column("errors", sa.JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_trading_cycle_reports_bot_started",
        "trading_cycle_reports",
        ["bot_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_trading_cycle_reports_bot_started", "trading_cycle_reports")
    op.drop_table("trading_cycle_reports")
    op.drop_index("ix_trading_bots_status", "trading_bots")
    op.drop_index("ix_trading_bots_account_id", "trading_bots")
    op.drop_table("trading_bots")
