"""governor actions audit table (P5)

Revision ID: 0002_governor
Revises: 0001_autonomy
Create Date: 2026-07-16

"""
import sqlalchemy as sa
from alembic import op

revision = "0002_governor"
down_revision = "0001_autonomy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autonomy_governor_actions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("strategy_key", sa.String(length=100), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("recommendation_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("autonomy_governor_actions")
