"""add knowledge agent run audit table

Revision ID: 20260704_0011
Revises: 20260613_0010
Create Date: 2026-07-04 12:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260704_0011"
down_revision: str | None = "20260613_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_agent_runs (
            id UUID PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            status VARCHAR(64) NOT NULL,
            model VARCHAR(255) NULL,
            confidence FLOAT NULL,
            allow_vision BOOLEAN NOT NULL DEFAULT false,
            max_steps INTEGER NOT NULL,
            tool_trace_json JSON NOT NULL,
            citations_json JSON NOT NULL,
            vision_requests_json JSON NOT NULL,
            duration_ms INTEGER NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_agent_runs_created_at "
        "ON knowledge_agent_runs (created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_agent_runs_status "
        "ON knowledge_agent_runs (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_agent_runs")
