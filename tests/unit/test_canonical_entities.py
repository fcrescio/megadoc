import pytest

from common.application.entities import (
    EntityVariantInput,
    assign_entity_variant,
    get_or_create_canonical_entity,
)


def test_entity_registry_is_idempotent_and_reassigns_variant(db_session):
    first = get_or_create_canonical_entity(
        db_session,
        entity_type="organizzazione",
        canonical_value="  Condominio   Studiati ",
        display_value="Condominio Studiati",
    )
    same = get_or_create_canonical_entity(
        db_session,
        entity_type="organizzazione",
        canonical_value="condominio studiati",
        display_value="CONDOMINIO STUDIATI",
    )
    assert same.id == first.id

    variant_input = EntityVariantInput(
        entity_type="organizzazione",
        entity_key="Condominio Via Studiati 6",
        display_value="Condominio Via Studiati 6",
    )
    variant = assign_entity_variant(db_session, first, variant_input)

    second = get_or_create_canonical_entity(
        db_session,
        entity_type="organizzazione",
        canonical_value="condominio studiati pisa",
        display_value="Condominio Studiati, Pisa",
        review_status="human_reviewed",
    )
    reassigned = assign_entity_variant(
        db_session,
        second,
        EntityVariantInput(
            entity_type="organizzazione",
            entity_key="condominio via studiati 6",
            display_value="Condominio Via Studiati 6",
            review_status="human_reviewed",
        ),
    )
    assert reassigned.id == variant.id
    assert reassigned.canonical_entity_id == second.id
    assert reassigned.review_status == "human_reviewed"
    assert len(first.variants) == 0


def test_entity_registry_rejects_cross_type_variant(db_session):
    entity = get_or_create_canonical_entity(
        db_session,
        entity_type="organizzazione",
        canonical_value="acque spa",
        display_value="Acque S.p.A.",
    )
    with pytest.raises(ValueError, match="entity_type"):
        assign_entity_variant(
            db_session,
            entity,
            EntityVariantInput(
                entity_type="persona",
                entity_key="acque spa",
                display_value="Acque S.p.A.",
            ),
        )
