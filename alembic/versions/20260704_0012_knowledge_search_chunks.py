"""add pgvector knowledge search chunks

Revision ID: 20260704_0012
Revises: 20260704_0011
Create Date: 2026-07-04 13:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260704_0012"
down_revision: str | None = "20260704_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_search_chunks (
            id UUID PRIMARY KEY,
            source_type VARCHAR(64) NOT NULL,
            source_id UUID NULL,
            document_id UUID NULL,
            document_unit_id UUID NULL,
            page_from INTEGER NULL,
            page_to INTEGER NULL,
            text TEXT NOT NULL,
            text_hash VARCHAR(64) NOT NULL,
            metadata_json JSON NOT NULL,
            embedding vector NOT NULL,
            embedding_model VARCHAR(255) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_knowledge_search_chunks_hash_model UNIQUE (text_hash, embedding_model)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_search_chunks_source "
        "ON knowledge_search_chunks (source_type, source_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_search_chunks_document "
        "ON knowledge_search_chunks (document_id, document_unit_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge_search_chunks")
