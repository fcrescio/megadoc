"""add unique constraint on topic assignments

Revision ID: 20260613_0008
Revises: 20260526_0007
Create Date: 2026-06-13 14:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260613_0008"
down_revision: str | None = "20260526_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deduplicate before adding constraint.
    # Strategy: keep the row with highest confidence, then most recent created_at,
    # then non-null rationale.
    op.execute("""
        DELETE FROM document_unit_topic_assignments a
        USING document_unit_topic_assignments b
        WHERE a.id < b.id
          AND a.document_unit_id = b.document_unit_id
          AND a.topic_id = b.topic_id
          AND a.assignment_role = b.assignment_role
          AND (
            a.confidence < b.confidence
            OR (a.confidence IS NULL AND b.confidence IS NOT NULL)
            OR (a.confidence IS NOT DISTINCT FROM b.confidence
                AND a.created_at < b.created_at)
            OR (a.confidence IS NOT DISTINCT FROM b.confidence
                AND a.created_at IS NOT DISTINCT FROM b.created_at
                AND a.rationale IS NULL AND b.rationale IS NOT NULL)
          )
    """)
    # Remove any remaining duplicates (same confidence/created_at) arbitrarily
    op.execute("""
        DELETE FROM document_unit_topic_assignments a
        USING document_unit_topic_assignments b
        WHERE a.id > b.id
          AND a.document_unit_id = b.document_unit_id
          AND a.topic_id = b.topic_id
          AND a.assignment_role = b.assignment_role
    """)
    op.create_unique_constraint(
        "uq_document_unit_topic_assignments_unit_topic_role",
        "document_unit_topic_assignments",
        ["document_unit_id", "topic_id", "assignment_role"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_document_unit_topic_assignments_unit_topic_role",
        "document_unit_topic_assignments",
    )
