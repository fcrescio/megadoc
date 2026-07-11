"""Add structured specialist routing metadata."""

import sqlalchemy as sa
from alembic import op

revision = "20260711_0016"
down_revision = "20260711_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("specialist_jobs", sa.Column("routing_confidence", sa.Float(), nullable=True))
    op.add_column("specialist_jobs", sa.Column("routing_rationale", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("specialist_jobs", "routing_rationale")
    op.drop_column("specialist_jobs", "routing_confidence")
