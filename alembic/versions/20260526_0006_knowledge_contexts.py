"""canonical knowledge contexts

Revision ID: 20260526_0006
Revises: 20260526_0005
Create Date: 2026-05-26 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260526_0006"
down_revision: str | None = "20260526_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_contexts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_kind", sa.String(length=32), server_default="entity", nullable=False),
        sa.Column("canonical_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("review_status", sa.String(length=32), server_default="auto", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["canonical_entity_id"], ["canonical_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("context_kind", "canonical_entity_id", name="uq_knowledge_contexts_kind_entity"),
    )
    op.create_index("ix_knowledge_contexts_kind_label", "knowledge_contexts", ["context_kind", "label"])
    op.create_table(
        "knowledge_context_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("context_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_role", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["context_id"], ["knowledge_contexts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_unit_id"], ["document_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("context_id", "document_unit_id", name="uq_knowledge_context_memberships_unit"),
    )
    op.create_index("ix_knowledge_context_memberships_unit", "knowledge_context_memberships", ["document_unit_id"])
    op.create_index(
        "ix_knowledge_context_memberships_context_role",
        "knowledge_context_memberships",
        ["context_id", "membership_role"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_context_memberships_context_role", table_name="knowledge_context_memberships")
    op.drop_index("ix_knowledge_context_memberships_unit", table_name="knowledge_context_memberships")
    op.drop_table("knowledge_context_memberships")
    op.drop_index("ix_knowledge_contexts_kind_label", table_name="knowledge_contexts")
    op.drop_table("knowledge_contexts")
