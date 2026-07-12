"""caller idempotency key on paper orders

Adds paper_orders.client_order_id (unique): execution-engine's deterministic
child client_order_id. Duplicate submissions replay the stored result
instead of filling twice. Nullable because pre-existing rows have no key.

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
        "paper_orders", sa.Column("client_order_id", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_paper_orders_client_order_id",
        "paper_orders",
        ["client_order_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_paper_orders_client_order_id", "paper_orders")
    op.drop_column("paper_orders", "client_order_id")
