"""idempotent client order ids

Adds the deterministic venue idempotency key (client_order_id) to
execution_child_orders (unique) and execution_reports. Nullable because
rows created before this revision have no derived key; all new rows set it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-11
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "execution_child_orders",
        sa.Column("client_order_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_execution_child_orders_client_order_id",
        "execution_child_orders",
        ["client_order_id"],
        unique=True,
    )
    op.add_column(
        "execution_reports",
        sa.Column("client_order_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_execution_reports_client_order_id",
        "execution_reports",
        ["client_order_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_execution_reports_client_order_id", "execution_reports")
    op.drop_column("execution_reports", "client_order_id")
    op.drop_index("ix_execution_child_orders_client_order_id", "execution_child_orders")
    op.drop_column("execution_child_orders", "client_order_id")
