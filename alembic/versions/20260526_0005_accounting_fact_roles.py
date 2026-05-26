"""accounting fact roles

Revision ID: 20260526_0005
Revises: 20260526_0004
Create Date: 2026-05-26 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260526_0005"
down_revision: str | None = "20260526_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounting_facts", sa.Column("accounting_role", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("accounting_facts", "accounting_role")
