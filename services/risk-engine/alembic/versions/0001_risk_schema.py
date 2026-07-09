"""initial risk-engine schema

Creates risk_engine_limits (mirrors init.sql `risk_limits` columns; own
table because init.sql's FKs to broker_accounts/users cannot be satisfied
by risk-engine and init.sql is read-only), risk_events (audit trail of
every rejection/halt) and circuit_breakers (per-account breaker state).

Revision ID: 0001
Revises:
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_engine_limits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False, unique=True),
        sa.Column("max_risk_per_trade", sa.Float, nullable=False),
        sa.Column("max_daily_loss", sa.Float, nullable=False),
        sa.Column("max_weekly_loss", sa.Float, nullable=False),
        sa.Column("max_monthly_loss", sa.Float, nullable=False),
        sa.Column("max_drawdown", sa.Float, nullable=False),
        sa.Column("max_floating_drawdown", sa.Float, nullable=False),
        sa.Column("max_leverage", sa.Float, nullable=False),
        sa.Column("max_correlation", sa.Float, nullable=False),
        sa.Column("max_exposure_per_symbol", sa.Float, nullable=False),
        sa.Column("max_exposure_per_sector", sa.Float, nullable=False),
        sa.Column("circuit_breaker_thresholds", sa.JSON, nullable=False),
        sa.Column("extra_limits", sa.JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "risk_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("signal_id", sa.String(36), nullable=True),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_risk_events_account_created", "risk_events", ["account_id", "created_at"])

    op.create_table(
        "circuit_breakers",
        sa.Column("account_id", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="NORMAL"),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("circuit_breakers")
    op.drop_index("ix_risk_events_account_created", "risk_events")
    op.drop_table("risk_events")
    op.drop_table("risk_engine_limits")
