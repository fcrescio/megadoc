"""initial schema

Revision ID: 20260422_0001
Revises:
Create Date: 2026-04-22 11:45:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260422_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=False)

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("storage_bucket", sa.String(length=255), nullable=False),
        sa.Column("storage_object_key", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_versions_doc_version"),
    )

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="5", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ingestion_jobs_status_created_at", "ingestion_jobs", ["status", "created_at"], unique=False)

    op.create_table(
        "ocr_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("engine_name", sa.String(length=64), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column("pipeline_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("markdown_text", sa.Text(), nullable=False),
        sa.Column("structured_json", sa.JSON(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("confidence_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ocr_results_document_created_at", "ocr_results", ["document_id", "created_at"], unique=False
    )

    op.create_table(
        "document_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("storage_bucket", sa.String(length=255), nullable=False),
        sa.Column("storage_object_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_assets_document_type", "document_assets", ["document_id", "asset_type"])


def downgrade() -> None:
    op.drop_index("ix_document_assets_document_type", table_name="document_assets")
    op.drop_table("document_assets")
    op.drop_index("ix_ocr_results_document_created_at", table_name="ocr_results")
    op.drop_table("ocr_results")
    op.drop_index("ix_ingestion_jobs_status_created_at", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_table("document_versions")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_table("documents")
