"""add review_payload_json to topic_proposals

Revision ID: 20260613_0010
Revises: 20260613_0009
Create Date: 2026-06-13 16:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260613_0010"
down_revision: str | None = "20260613_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE topic_proposals ADD COLUMN IF NOT EXISTS review_payload_json JSON NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE topic_proposals DROP COLUMN IF EXISTS review_payload_json")
