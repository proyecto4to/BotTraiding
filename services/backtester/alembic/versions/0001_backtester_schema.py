"""initial backtester schema

Creates the backtester-owned tables: backtester_runs, backtester_results.
Column shapes mirror infra/docker/init.sql `backtest_runs` /
`backtest_results` where compatible (status/parameters/started_at/
finished_at; metrics/created_at/backtest_run_id). Table names are prefixed
because init.sql's backtest_runs is keyed by strategy_version_id UUID (FK
to `strategy_versions`) which the backtester cannot resolve in Fase 8 -
runs are keyed by the shared registry's strategy_key string instead.

Revision ID: 0001
Revises:
Create Date: 2026-07-10
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
        "backtester_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("strategy_key", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=True),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("initial_capital", sa.Float, nullable=False),
        sa.Column("parameters", sa.JSON, nullable=False),
        sa.Column("friction", sa.JSON, nullable=False),
        sa.Column("data_config", sa.JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_backtester_runs_strategy_key", "backtester_runs", ["strategy_key"])

    op.create_table(
        "backtester_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "backtest_run_id",
            sa.String(36),
            sa.ForeignKey("backtester_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metrics", sa.JSON, nullable=False),
        sa.Column("equity_curve", sa.JSON, nullable=False),
        sa.Column("trades", sa.JSON, nullable=False),
        sa.Column("stats", sa.JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_backtester_results_backtest_run_id", "backtester_results", ["backtest_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_backtester_results_backtest_run_id", "backtester_results")
    op.drop_table("backtester_results")
    op.drop_index("ix_backtester_runs_strategy_key", "backtester_runs")
    op.drop_table("backtester_runs")
