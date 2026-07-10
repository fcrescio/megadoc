"""normalize topics as curated collections

Revision ID: 20260711_0014
Revises: 20260710_0013
Create Date: 2026-07-11 09:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260711_0014"
down_revision: str | None = "20260710_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TOPIC_KIND_SQL = """
CASE topic_class
    WHEN 'financial_period' THEN 'family'
    WHEN 'meeting' THEN 'family'
    WHEN 'vendor_relationship' THEN 'family'
    WHEN 'general_administration' THEN 'family'
    WHEN 'building_issue' THEN 'issue'
    WHEN 'legal_matter' THEN 'issue'
    WHEN 'case_file' THEN 'project'
    WHEN 'other' THEN 'context'
    ELSE 'context'
END
"""


def upgrade() -> None:
    op.execute("ALTER TABLE topics ALTER COLUMN topic_kind SET DEFAULT 'context'")
    op.execute("ALTER TABLE topic_proposals ALTER COLUMN proposed_topic_kind SET DEFAULT 'context'")
    op.execute(
        f"""
        UPDATE topics
        SET topic_kind = {_TOPIC_KIND_SQL}
        WHERE topic_kind IS NULL OR topic_kind = 'entity'
        """
    )
    op.execute(
        f"""
        UPDATE topic_proposals
        SET proposed_topic_kind = {_TOPIC_KIND_SQL}
        WHERE proposed_topic_kind IS NULL OR proposed_topic_kind = 'entity'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE topics ALTER COLUMN topic_kind SET DEFAULT 'entity'")
    op.execute("ALTER TABLE topic_proposals ALTER COLUMN proposed_topic_kind SET DEFAULT 'entity'")
