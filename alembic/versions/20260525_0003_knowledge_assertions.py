"""knowledge graph assertions

Revision ID: 20260525_0003
Revises: 20260422_0002
Create Date: 2026-05-25 20:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260525_0003"
down_revision: str | None = "20260422_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_kind", sa.String(length=32), nullable=False),
        sa.Column("canonical_key", sa.String(length=512), nullable=False),
        sa.Column("label", sa.String(length=512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=32), server_default="auto", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_kind", "canonical_key", name="uq_knowledge_nodes_kind_key"),
    )
    op.create_index("ix_knowledge_nodes_kind_label", "knowledge_nodes", ["node_kind", "label"])

    op.create_table(
        "knowledge_node_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=512), nullable=False),
        sa.Column("normalized_alias", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("node_id", "normalized_alias", name="uq_knowledge_node_aliases_node_alias"),
    )
    op.create_index("ix_knowledge_node_aliases_normalized", "knowledge_node_aliases", ["normalized_alias"])

    op.create_table(
        "knowledge_predicates",
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("value_kind", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_facetable", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code"),
    )

    op.create_table(
        "document_unit_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mention_role", sa.String(length=32), server_default="mentioned", nullable=False),
        sa.Column("source_type", sa.String(length=32), server_default="entity", nullable=False),
        sa.Column("surface_text", sa.String(length=512), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_unit_id"], ["document_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_unit_mentions_unit", "document_unit_mentions", ["document_unit_id"])
    op.create_index("ix_document_unit_mentions_node", "document_unit_mentions", ["node_id"])

    op.create_table(
        "knowledge_assertions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("predicate_code", sa.String(length=64), nullable=False),
        sa.Column("subject_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("object_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("value_text", sa.String(length=1024), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("review_status", sa.String(length=32), server_default="auto", nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("specialist_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_unit_id"], ["document_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["predicate_code"], ["knowledge_predicates.code"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subject_node_id"], ["knowledge_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["object_node_id"], ["knowledge_nodes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_assertions_unit_predicate",
        "knowledge_assertions",
        ["document_unit_id", "predicate_code"],
    )
    op.create_index(
        "ix_knowledge_assertions_subject_predicate",
        "knowledge_assertions",
        ["subject_node_id", "predicate_code"],
    )
    op.create_index(
        "ix_knowledge_assertions_object_predicate",
        "knowledge_assertions",
        ["object_node_id", "predicate_code"],
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.specialist_results') IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'knowledge_assertions'::regclass
                     AND confrelid = 'specialist_results'::regclass
               )
            THEN
                ALTER TABLE knowledge_assertions
                ADD CONSTRAINT fk_knowledge_assertions_specialist_result
                FOREIGN KEY (specialist_result_id) REFERENCES specialist_results(id) ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_assertions_object_predicate", table_name="knowledge_assertions")
    op.drop_index("ix_knowledge_assertions_subject_predicate", table_name="knowledge_assertions")
    op.drop_index("ix_knowledge_assertions_unit_predicate", table_name="knowledge_assertions")
    op.drop_table("knowledge_assertions")
    op.drop_index("ix_document_unit_mentions_node", table_name="document_unit_mentions")
    op.drop_index("ix_document_unit_mentions_unit", table_name="document_unit_mentions")
    op.drop_table("document_unit_mentions")
    op.drop_table("knowledge_predicates")
    op.drop_index("ix_knowledge_node_aliases_normalized", table_name="knowledge_node_aliases")
    op.drop_table("knowledge_node_aliases")
    op.drop_index("ix_knowledge_nodes_kind_label", table_name="knowledge_nodes")
    op.drop_table("knowledge_nodes")
