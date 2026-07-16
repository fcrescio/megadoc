"""add lexical indexes to knowledge search chunks

Revision ID: 20260716_0018
Revises: 20260711_0017
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260716_0018"
down_revision: str | None = "20260711_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_search_chunks_fts "
        "ON knowledge_search_chunks USING gin (to_tsvector('simple', text))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_search_chunks_trgm "
        "ON knowledge_search_chunks USING gin (text gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_search_chunks_trgm")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_search_chunks_fts")
