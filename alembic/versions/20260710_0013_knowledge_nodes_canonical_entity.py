"""link knowledge nodes to canonical entities

Revision ID: 20260710_0013
Revises: 20260704_0012
Create Date: 2026-07-10 22:30:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260710_0013"
down_revision: str | None = "20260704_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_nodes ADD COLUMN IF NOT EXISTS canonical_entity_id UUID NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.canonical_entities') IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM pg_constraint
                   WHERE conname = 'fk_knowledge_nodes_canonical_entity'
               )
            THEN
                ALTER TABLE knowledge_nodes
                ADD CONSTRAINT fk_knowledge_nodes_canonical_entity
                FOREIGN KEY (canonical_entity_id) REFERENCES canonical_entities(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_nodes_canonical_entity "
        "ON knowledge_nodes(canonical_entity_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_nodes_canonical_entity")
    op.execute("ALTER TABLE knowledge_nodes DROP CONSTRAINT IF EXISTS fk_knowledge_nodes_canonical_entity")
    op.execute("ALTER TABLE knowledge_nodes DROP COLUMN IF EXISTS canonical_entity_id")
