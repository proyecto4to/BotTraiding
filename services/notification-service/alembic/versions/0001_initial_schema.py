"""initial notification-service schema

Service-owned tables (init.sql's generic `notifications` table is read-only
and does not match this service's routing model — see app/models.py):
notification_messages, notification_preferences, notification_dead_letters.
Version table: alembic_version_notification.

Revision ID: 0001
Revises:
Create Date: 2026-07-11
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
        "notification_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("account_id", sa.String(64), nullable=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False, server_default=""),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_notification_messages_user_id", "notification_messages", ["user_id"]
    )
    op.create_index(
        "ix_notification_messages_severity", "notification_messages", ["severity"]
    )
    op.create_index(
        "ix_notification_messages_status", "notification_messages", ["status"]
    )
    op.create_index(
        "ix_notification_messages_created_at", "notification_messages", ["created_at"]
    )

    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("subjects", sa.JSON, nullable=False),
        sa.Column("account_ids", sa.JSON, nullable=False),
        sa.Column("email_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("email_address", sa.String(255), nullable=True),
        sa.Column("email_min_severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("telegram_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("telegram_chat_id", sa.String(64), nullable=True),
        sa.Column("telegram_min_severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("webhook_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("webhook_url", sa.String(1024), nullable=True),
        sa.Column("webhook_secret", sa.String(255), nullable=True),
        sa.Column("webhook_min_severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "notification_dead_letters",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "notification_id",
            sa.String(36),
            sa.ForeignKey("notification_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("target", sa.String(1024), nullable=True),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_notification_dead_letters_user_id", "notification_dead_letters", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notification_dead_letters_user_id", table_name="notification_dead_letters")
    op.drop_table("notification_dead_letters")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notification_messages_created_at", table_name="notification_messages")
    op.drop_index("ix_notification_messages_status", table_name="notification_messages")
    op.drop_index("ix_notification_messages_severity", table_name="notification_messages")
    op.drop_index("ix_notification_messages_user_id", table_name="notification_messages")
    op.drop_table("notification_messages")
