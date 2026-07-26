"""track the worst drawdown ever observed per account

current_drawdown only describes the present moment, so an account that fell 40%
and recovered looked spotless to the paper->live promotion gate. max_drawdown is
a high-water mark that never decreases, and it is what the gate now reads.

Backfilled to 0 for existing rows: the history needed to reconstruct the real
worst drawdown was never recorded, and 0 is the value that keeps the gate honest
by forcing a fresh observation period rather than inventing a past.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26
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
        "portfolio_accounts",
        sa.Column("max_drawdown", sa.Float, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("portfolio_accounts", "max_drawdown")
