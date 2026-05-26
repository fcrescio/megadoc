"""accounting facts projection

Revision ID: 20260526_0004
Revises: 20260525_0003
Create Date: 2026-05-26 08:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260526_0004"
down_revision: str | None = "20260525_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "accounting_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_node_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope_key", sa.String(length=512), nullable=False),
        sa.Column("account_key", sa.String(length=512), nullable=False),
        sa.Column("unit_code", sa.String(length=64), nullable=True),
        sa.Column("subject_label", sa.String(length=512), nullable=False),
        sa.Column("review_status", sa.String(length=32), server_default="auto", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["scope_node_id"], ["knowledge_nodes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_key", "account_key", name="uq_accounting_accounts_scope_key"),
    )
    op.create_index("ix_accounting_accounts_label_unit", "accounting_accounts", ["subject_label", "unit_code"])

    op.create_table(
        "accounting_account_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=512), nullable=False),
        sa.Column("normalized_alias", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounting_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "normalized_alias",
            name="uq_accounting_account_aliases_account_alias",
        ),
    )
    op.create_index("ix_accounting_account_aliases_normalized", "accounting_account_aliases", ["normalized_alias"])

    op.create_table(
        "accounting_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("specialist_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fact_type", sa.String(length=64), nullable=False),
        sa.Column("category_key", sa.String(length=512), nullable=True),
        sa.Column("category_label", sa.String(length=512), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("raw_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="EUR", nullable=False),
        sa.Column("period_context_from", sa.Date(), nullable=True),
        sa.Column("period_context_to", sa.Date(), nullable=True),
        sa.Column("period_source", sa.String(length=32), nullable=True),
        sa.Column("period_review_status", sa.String(length=32), nullable=True),
        sa.Column("is_total", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("review_status", sa.String(length=32), server_default="auto", nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_unit_id"], ["document_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounting_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounting_facts_account_type", "accounting_facts", ["account_id", "fact_type"])
    op.create_index("ix_accounting_facts_unit_type", "accounting_facts", ["document_unit_id", "fact_type"])
    op.create_index("ix_accounting_facts_category", "accounting_facts", ["category_key"])
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.specialist_results') IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM pg_constraint
                   WHERE conrelid = 'accounting_facts'::regclass
                     AND confrelid = 'specialist_results'::regclass
               )
            THEN
                ALTER TABLE accounting_facts
                ADD CONSTRAINT fk_accounting_facts_specialist_result
                FOREIGN KEY (specialist_result_id) REFERENCES specialist_results(id) ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_accounting_facts_category", table_name="accounting_facts")
    op.drop_index("ix_accounting_facts_unit_type", table_name="accounting_facts")
    op.drop_index("ix_accounting_facts_account_type", table_name="accounting_facts")
    op.drop_table("accounting_facts")
    op.drop_index("ix_accounting_account_aliases_normalized", table_name="accounting_account_aliases")
    op.drop_table("accounting_account_aliases")
    op.drop_index("ix_accounting_accounts_label_unit", table_name="accounting_accounts")
    op.drop_table("accounting_accounts")
