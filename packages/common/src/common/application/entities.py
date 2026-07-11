from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import CanonicalEntity, CanonicalEntityVariant


@dataclass(frozen=True)
class EntityVariantInput:
    entity_type: str
    entity_key: str
    display_value: str
    review_status: str = "auto"


def normalize_entity_key(value: str) -> str:
    return " ".join(value.strip().lower().split())


def get_or_create_canonical_entity(
    session: Session,
    *,
    entity_type: str,
    canonical_value: str,
    display_value: str,
    review_status: str = "auto",
) -> CanonicalEntity:
    canonical_key = normalize_entity_key(canonical_value)
    entity = session.execute(
        select(CanonicalEntity).where(
            CanonicalEntity.entity_type == entity_type,
            CanonicalEntity.canonical_value == canonical_key,
        )
    ).scalar_one_or_none()
    if entity is None:
        entity = CanonicalEntity(
            entity_type=entity_type,
            canonical_value=canonical_key,
            display_value=display_value.strip() or canonical_key,
            review_status=review_status,
        )
        session.add(entity)
        session.flush()
    elif review_status != "auto" and entity.review_status == "auto":
        entity.review_status = review_status
        entity.updated_at = datetime.now(timezone.utc)
    return entity


def assign_entity_variant(
    session: Session,
    canonical_entity: CanonicalEntity,
    variant: EntityVariantInput,
) -> CanonicalEntityVariant:
    """Assign one local identity key to exactly one canonical identity."""
    entity_key = normalize_entity_key(variant.entity_key)
    if not entity_key:
        raise ValueError("entity_key must not be empty")
    if variant.entity_type != canonical_entity.entity_type:
        raise ValueError("variant entity_type must match canonical entity_type")

    existing = session.execute(
        select(CanonicalEntityVariant).where(
            CanonicalEntityVariant.entity_type == variant.entity_type,
            CanonicalEntityVariant.entity_key == entity_key,
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing is None:
        existing = CanonicalEntityVariant(
            canonical_entity_id=canonical_entity.id,
            entity_type=variant.entity_type,
            entity_key=entity_key,
            display_value=variant.display_value.strip() or entity_key,
            review_status=variant.review_status,
        )
        session.add(existing)
    else:
        existing.canonical_entity_id = canonical_entity.id
        existing.display_value = variant.display_value.strip() or existing.display_value
        if variant.review_status != "auto" or existing.review_status == "auto":
            existing.review_status = variant.review_status
        existing.updated_at = now
    session.flush()
    return existing
