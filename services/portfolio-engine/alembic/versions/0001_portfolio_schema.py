"""initial portfolio-engine schema

Creates the portfolio-engine-owned tables: portfolio_accounts,
portfolio_positions, portfolio_executions. Column shapes mirror
infra/docker/init.sql `positions` / `executions` where relevant; table
names are prefixed because init.sql's tables are keyed by symbol_id UUID
(FK to `symbols`) which portfolio-engine cannot resolve in Fase 7.

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
        "portfolio_accounts",
        sa.Column("account_id", sa.String(64), primary_key=True),
        sa.Column("cash", sa.Float, nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("peak_equity", sa.Float, nullable=False, server_default="0"),
        sa.Column("base_currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(64),
            sa.ForeignKey("portfolio_accounts.account_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False, server_default="0"),
        sa.Column("average_price", sa.Float, nullable=False, server_default="0"),
        sa.Column("last_price", sa.Float, nullable=True),
        sa.Column("unrealized_pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("account_id", "symbol", name="uq_portfolio_position"),
    )

    op.create_table(
        "portfolio_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(64),
            sa.ForeignKey("portfolio_accounts.account_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("filled_quantity", sa.Float, nullable=False, server_default="0"),
        sa.Column("average_fill_price", sa.Float, nullable=True),
        sa.Column("commission", sa.Float, nullable=False, server_default="0"),
        sa.Column("realized_pnl", sa.Float, nullable=False, server_default="0"),
        sa.Column("raw", sa.JSON, nullable=False),
        sa.Column(
            "reported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_portfolio_executions_account_reported",
        "portfolio_executions",
        ["account_id", "reported_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_executions_account_reported", "portfolio_executions")
    op.drop_table("portfolio_executions")
    op.drop_table("portfolio_positions")
    op.drop_table("portfolio_accounts")
