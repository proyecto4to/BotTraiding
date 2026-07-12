"""broker_credentials (encrypted API keys)

Revision ID: 0001_broker_credentials
Revises:
Create Date: 2026-07-12

"""
from alembic import op
import sqlalchemy as sa

revision = "0001_broker_credentials"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broker_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("broker", sa.String(length=50), nullable=False),
        sa.Column("account_id", sa.String(length=64), nullable=False, server_default="default"),
        sa.Column("encrypted_blob", sa.Text(), nullable=False),
        sa.Column("demo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("rotated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "broker", "account_id", name="uq_broker_credentials_broker_account"
        ),
    )


def downgrade() -> None:
    op.drop_table("broker_credentials")
