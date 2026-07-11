"""Add canonical payable projection."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260711_0017"
down_revision = "20260711_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payables",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_document_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_specialist_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("duplicate_of_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payable_kind", sa.String(32), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=True),
        sa.Column("recipient", sa.String(512), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(8), nullable=True),
        sa.Column("payment_reference", sa.String(512), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("deduplication_fingerprint", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="needs_review"),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_document_unit_id"], ["document_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_specialist_result_id"], ["specialist_results.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["payables.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source_specialist_result_id", name="uq_payables_source_result"),
    )
    op.create_index("ix_payables_due_date", "payables", ["due_date"])
    op.create_index("ix_payables_issuer", "payables", ["issuer"])
    op.create_index("ix_payables_status", "payables", ["status"])
    op.create_index("ix_payables_fingerprint", "payables", ["deduplication_fingerprint"])


def downgrade() -> None:
    op.drop_table("payables")
