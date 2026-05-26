"""knowledge context anchors

Revision ID: 20260526_0007
Revises: 20260526_0006
Create Date: 2026-05-26 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260526_0007"
down_revision: str | None = "20260526_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_context_anchors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anchor_role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["context_id"], ["knowledge_contexts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["canonical_entity_id"], ["canonical_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("context_id", "canonical_entity_id", name="uq_knowledge_context_anchors_entity"),
    )
    op.create_index("ix_knowledge_context_anchors_entity", "knowledge_context_anchors", ["canonical_entity_id"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_context_anchors_entity", table_name="knowledge_context_anchors")
    op.drop_table("knowledge_context_anchors")
