"""initial execution-engine schema

Creates executions (parent record per approved Order, with the approving
RiskDecision frozen in for audit), execution_child_orders (order-splitting
slices) and execution_reports (every ExecutionReport produced by a
transport). Version table is alembic_version_execution.

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
        "executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("signal_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("price", sa.Float, nullable=True),
        sa.Column("broker", sa.String(64), nullable=False),
        sa.Column("execution_mode", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("filled_quantity", sa.Float, nullable=False, server_default="0"),
        sa.Column("average_fill_price", sa.Float, nullable=True),
        sa.Column("risk_decision", sa.JSON, nullable=False),
        sa.Column("requested_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_executions_order", "executions", ["order_id"])
    op.create_index("ix_executions_account_created", "executions", ["account_id", "created_at"])

    op.create_table(
        "execution_child_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id", sa.String(36), sa.ForeignKey("executions.id"), nullable=False
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("filled_quantity", sa.Float, nullable=False, server_default="0"),
        sa.Column("average_fill_price", sa.Float, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_execution_child_orders_execution", "execution_child_orders", ["execution_id"]
    )

    op.create_table(
        "execution_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id", sa.String(36), sa.ForeignKey("executions.id"), nullable=False
        ),
        sa.Column("child_order_id", sa.String(36), nullable=False),
        sa.Column("report_order_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("filled_quantity", sa.Float, nullable=False, server_default="0"),
        sa.Column("average_fill_price", sa.Float, nullable=True),
        sa.Column("broker", sa.String(64), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", sa.JSON, nullable=False),
        sa.Column(
            "forwarded_to_portfolio", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_execution_reports_execution", "execution_reports", ["execution_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_reports_execution", "execution_reports")
    op.drop_table("execution_reports")
    op.drop_index("ix_execution_child_orders_execution", "execution_child_orders")
    op.drop_table("execution_child_orders")
    op.drop_index("ix_executions_account_created", "executions")
    op.drop_index("ix_executions_order", "executions")
    op.drop_table("executions")
