"""Enforce one canonical owner for each entity variant."""

from alembic import op

revision = "20260711_0015"
down_revision = "20260711_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_canonical_entities_type_value",
        "canonical_entities",
        ["entity_type", "canonical_value"],
    )
    op.create_unique_constraint(
        "uq_canonical_entity_variants_type_key",
        "canonical_entity_variants",
        ["entity_type", "entity_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_canonical_entity_variants_type_key",
        "canonical_entity_variants",
        type_="unique",
    )
    op.drop_constraint(
        "uq_canonical_entities_type_value",
        "canonical_entities",
        type_="unique",
    )
