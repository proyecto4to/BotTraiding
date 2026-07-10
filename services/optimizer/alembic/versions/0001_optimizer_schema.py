"""initial optimizer schema

Reproduces infra/docker/init.sql's optimization_runs/optimization_results
tables where compatible, extended with the Fase 12 walk-forward and
promotion-decision columns. init.sql itself is never edited (owned by
infra); this migration is the optimizer-owned source of truth, applied by
docker-entrypoint.sh with version_table "alembic_version_optimizer".

Ownership deviation from init.sql: runs are keyed by the shared
code-registry strategy_key (plus a plain strategy_version string) instead
of a strategy_version_id FK into strategy-engine's tables - services
never depend on each other's tables (docs/ARCHITECTURE.md, principle 1).

Revision ID: 0001
Revises:
Create Date: 2026-07-10
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
        "optimization_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("strategy_key", sa.String(100), nullable=False),
        sa.Column("strategy_version", sa.String(50), nullable=True),
        sa.Column("symbol", sa.String(50), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "search_type", sa.String(10), nullable=False, server_default="grid"
        ),
        sa.Column("budget", sa.Integer, nullable=False, server_default="16"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "search_space", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "baseline_params", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("best_params", postgresql.JSONB, nullable=True),
        sa.Column("promoted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("applied", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "decision", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_optimization_runs_strategy_key", "optimization_runs", ["strategy_key"]
    )

    op.create_table(
        "optimization_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "optimization_run_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("optimization_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parameters", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "metrics", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "out_of_sample", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("window_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "role", sa.String(20), nullable=False, server_default="candidate"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_optimization_results_run", "optimization_results", ["optimization_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_optimization_results_run", table_name="optimization_results")
    op.drop_table("optimization_results")
    op.drop_index("ix_optimization_runs_strategy_key", table_name="optimization_runs")
    op.drop_table("optimization_runs")
