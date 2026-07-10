"""initial ai-engine schema

Creates `ai_recommendations`: every advisory recommendation the AI engine
emits (e.g. disable an underperforming strategy) is persisted here with
its rule, reason, severity and backing metrics. The AI engine never acts
on its own recommendations; consumers read GET /ai/recommendations or the
`ai.recommendation.created` NATS event.

init.sql itself is never edited (owned by infra); this migration is the
ai-engine-owned source of truth, applied by docker-entrypoint.sh with
version_table "alembic_version_ai" so it never collides with other
services. strategy_key is the shared code-registry key (no cross-service
FK - strategy-engine owns the strategies table, principle 1).

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
        "ai_recommendations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("strategy_key", sa.String(100), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("rule", sa.String(100), nullable=False, server_default=""),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "severity", sa.String(20), nullable=False, server_default="medium"
        ),
        sa.Column(
            "metrics", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_ai_recommendations_strategy_key",
        "ai_recommendations",
        ["strategy_key"],
    )
    op.create_index(
        "ix_ai_recommendations_created_at",
        "ai_recommendations",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_recommendations_created_at", table_name="ai_recommendations"
    )
    op.drop_index(
        "ix_ai_recommendations_strategy_key", table_name="ai_recommendations"
    )
    op.drop_table("ai_recommendations")
