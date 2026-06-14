"""add archive_identity_json to document_units

Revision ID: 20260613_0009
Revises: 20260613_0008
Create Date: 2026-06-13 15:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260613_0009"
down_revision: str | None = "20260613_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE document_units ADD COLUMN IF NOT EXISTS archive_identity_json JSON NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE document_units DROP COLUMN IF EXISTS archive_identity_json")
