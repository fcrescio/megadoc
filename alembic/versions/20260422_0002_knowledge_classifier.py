"""knowledge classifier schema

Revision ID: 20260422_0002
Revises: 20260422_0001
Create Date: 2026-04-22 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260422_0002"
down_revision: str | None = "20260422_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Document types
    op.create_table(
        "document_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_code", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_document_types_code", "document_types", ["code"], unique=True)
    op.create_index("ix_document_types_active", "document_types", ["is_active"])

    # Topics
    op.create_table(
        "topics",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("topic_class", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("canonical", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_topics_slug", "topics", ["slug"], unique=True)
    op.create_index("ix_topics_class", "topics", ["topic_class"])
    op.create_index("ix_topics_active", "topics", ["is_active"])

    # Topic aliases
    op.create_table(
        "topic_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_topic_aliases_alias", "topic_aliases", ["alias"])

    # Topic proposals
    op.create_table(
        "topic_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposed_slug", sa.String(length=255), nullable=False),
        sa.Column("proposed_title", sa.String(length=512), nullable=False),
        sa.Column("topic_class", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("proposal_status", sa.String(length=32), nullable=False),
        sa.Column("source_document_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("matched_existing_topic_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_topic_proposals_status", "topic_proposals", ["proposal_status"])
    op.create_index("ix_topic_proposals_slug", "topic_proposals", ["proposed_slug"])

    # Scan units
    op.create_table(
        "scan_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_document_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_ocr_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("segmentation_confidence", sa.Float(), nullable=True),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("assignment_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_document_version_id"], ["document_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_ocr_result_id"], ["ocr_results.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_units_status", "scan_units", ["status"])
    op.create_index("ix_scan_units_document", "scan_units", ["source_document_id"])
    op.create_index("ix_scan_units_ocr", "scan_units", ["source_ocr_result_id"])

    # Document units
    op.create_table(
        "document_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_page", sa.Integer(), nullable=False),
        sa.Column("end_page", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("document_type_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_type_confidence", sa.Float(), nullable=True),
        sa.Column("segmentation_confidence", sa.Float(), nullable=True),
        sa.Column("extracted_summary", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["scan_unit_id"], ["scan_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_type_id"], ["document_types.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_units_scan", "document_units", ["scan_unit_id"])
    op.create_index("ix_document_units_type", "document_units", ["document_type_id"])
    op.create_index("ix_document_units_review", "document_units", ["review_status"])

    # Document unit entities
    op.create_table(
        "document_unit_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_value", sa.String(length=512), nullable=False),
        sa.Column("normalized_value", sa.String(length=512), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("page_from", sa.Integer(), nullable=True),
        sa.Column("page_to", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_unit_id"], ["document_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entities_unit", "document_unit_entities", ["document_unit_id"])
    op.create_index("ix_entities_type", "document_unit_entities", ["entity_type"])

    # Document unit topic assignments
    op.create_table(
        "document_unit_topic_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_role", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_unit_id"], ["document_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assignments_unit", "document_unit_topic_assignments", ["document_unit_id"])
    op.create_index("ix_assignments_topic", "document_unit_topic_assignments", ["topic_id"])

    # Knowledge jobs
    op.create_table(
        "knowledge_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scan_unit_id"], ["scan_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_jobs_status", "knowledge_jobs", ["status"])
    op.create_index("ix_knowledge_jobs_scan", "knowledge_jobs", ["scan_unit_id"])

    # LLM decisions
    op.create_table(
        "llm_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("document_unit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decision_type", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("input_payload_json", sa.JSON(), nullable=False),
        sa.Column("output_payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["scan_unit_id"], ["scan_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_unit_id"], ["document_units.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_decisions_type", "llm_decisions", ["decision_type"])
    op.create_index("ix_llm_decisions_scan", "llm_decisions", ["scan_unit_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_decisions_scan", table_name="llm_decisions")
    op.drop_index("ix_llm_decisions_type", table_name="llm_decisions")
    op.drop_table("llm_decisions")

    op.drop_index("ix_knowledge_jobs_scan", table_name="knowledge_jobs")
    op.drop_index("ix_knowledge_jobs_status", table_name="knowledge_jobs")
    op.drop_table("knowledge_jobs")

    op.drop_index("ix_assignments_topic", table_name="document_unit_topic_assignments")
    op.drop_index("ix_assignments_unit", table_name="document_unit_topic_assignments")
    op.drop_table("document_unit_topic_assignments")

    op.drop_index("ix_entities_type", table_name="document_unit_entities")
    op.drop_index("ix_entities_unit", table_name="document_unit_entities")
    op.drop_table("document_unit_entities")

    op.drop_index("ix_document_units_review", table_name="document_units")
    op.drop_index("ix_document_units_type", table_name="document_units")
    op.drop_index("ix_document_units_scan", table_name="document_units")
    op.drop_table("document_units")

    op.drop_index("ix_scan_units_ocr", table_name="scan_units")
    op.drop_index("ix_scan_units_document", table_name="scan_units")
    op.drop_index("ix_scan_units_status", table_name="scan_units")
    op.drop_table("scan_units")

    op.drop_index("ix_topic_proposals_slug", table_name="topic_proposals")
    op.drop_index("ix_topic_proposals_status", table_name="topic_proposals")
    op.drop_table("topic_proposals")

    op.drop_index("ix_topic_aliases_alias", table_name="topic_aliases")
    op.drop_table("topic_aliases")

    op.drop_index("ix_topics_active", table_name="topics")
    op.drop_index("ix_topics_class", table_name="topics")
    op.drop_index("ix_topics_slug", table_name="topics")
    op.drop_table("topics")

    op.drop_index("ix_document_types_active", table_name="document_types")
    op.drop_index("ix_document_types_code", table_name="document_types")
    op.drop_table("document_types")
