"""add trading_bots.risk_allocation (P7 capital allocation)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-13

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trading_bots", sa.Column("risk_allocation", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("trading_bots", "risk_allocation")
