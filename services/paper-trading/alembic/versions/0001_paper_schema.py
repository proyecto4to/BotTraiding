"""initial paper-trading schema

Creates paper_accounts (simulated cash accounts), paper_positions and
paper_orders. Version table is alembic_version_paper so this history never
collides with other services sharing the same Postgres database.

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
        "paper_accounts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("starting_cash", sa.Float, nullable=False),
        sa.Column("cash", sa.Float, nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "paper_positions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False, server_default="0"),
        sa.Column("average_price", sa.Float, nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("account_id", "symbol", name="uq_paper_position"),
    )
    op.create_index("ix_paper_positions_account", "paper_positions", ["account_id"])

    op.create_table(
        "paper_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False, server_default="market"),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("filled_quantity", sa.Float, nullable=False, server_default="0"),
        sa.Column("average_fill_price", sa.Float, nullable=True),
        sa.Column("reference_price", sa.Float, nullable=False),
        sa.Column("commission", sa.Float, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("raw", sa.JSON, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_paper_orders_account", "paper_orders", ["account_id"])


def downgrade() -> None:
    op.drop_index("ix_paper_orders_account", "paper_orders")
    op.drop_table("paper_orders")
    op.drop_index("ix_paper_positions_account", "paper_positions")
    op.drop_table("paper_positions")
    op.drop_table("paper_accounts")
