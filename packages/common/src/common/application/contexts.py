from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from common.db.models import (
    CanonicalEntity,
    DocumentUnit,
    KnowledgeContext,
    KnowledgeContextMembership,
)


@dataclass
class ContextProjectionStats:
    contexts: int
    memberships: int


@dataclass
class _DirectMatch:
    entity: CanonicalEntity
    confidence: float | None
    surface_text: str


STABLE_REVIEW_STATUSES = {"human_reviewed", "corrected"}


def rebuild_knowledge_contexts(session: Session) -> ContextProjectionStats:
    """Rebuild stable archive contexts from reconciled entities.

    Contexts are created only for reviewed entities or identities repeated in
    multiple source documents. This keeps one-off extraction noise out of the
    navigation layer while allowing corrections to be projected deterministically.
    """
    session.execute(delete(KnowledgeContextMembership))
    session.execute(delete(KnowledgeContext))

    canonical_entities = session.execute(
        select(CanonicalEntity).options(selectinload(CanonicalEntity.variants))
    ).scalars().unique().all()
    variants = {
        (variant.entity_type, variant.entity_key.strip().lower()): entity
        for entity in canonical_entities
        for variant in entity.variants
    }
    units = session.execute(
        select(DocumentUnit)
        .options(selectinload(DocumentUnit.entities), selectinload(DocumentUnit.scan_unit))
        .order_by(DocumentUnit.created_at.asc())
    ).scalars().unique().all()

    direct_by_unit: dict[uuid.UUID, dict[uuid.UUID, _DirectMatch]] = {}
    unit_by_id = {unit.id: unit for unit in units}
    unit_ids_by_document: dict[uuid.UUID, list[uuid.UUID]] = {}
    documents_by_entity: dict[uuid.UUID, set[uuid.UUID]] = {}
    source_units_by_entity: dict[tuple[uuid.UUID, uuid.UUID], set[uuid.UUID]] = {}

    for unit in units:
        source_document_id = unit.scan_unit.source_document_id
        unit_ids_by_document.setdefault(source_document_id, []).append(unit.id)
        matches: dict[uuid.UUID, _DirectMatch] = {}
        for extracted in unit.entities:
            key = (extracted.normalized_value or extracted.entity_value).strip().lower()
            canonical = variants.get((extracted.entity_type, key))
            if canonical is None:
                continue
            current = matches.get(canonical.id)
            if current is None or (extracted.confidence or 0) > (current.confidence or 0):
                matches[canonical.id] = _DirectMatch(
                    entity=canonical,
                    confidence=extracted.confidence,
                    surface_text=extracted.entity_value,
                )
        direct_by_unit[unit.id] = matches
        for entity_id in matches:
            documents_by_entity.setdefault(entity_id, set()).add(source_document_id)
            source_units_by_entity.setdefault((source_document_id, entity_id), set()).add(unit.id)

    eligible_entities = {
        entity.id: entity
        for entity in canonical_entities
        if entity.review_status in STABLE_REVIEW_STATUSES or len(documents_by_entity.get(entity.id, set())) >= 2
    }
    contexts: dict[uuid.UUID, KnowledgeContext] = {}
    for entity_id, entity in eligible_entities.items():
        context = KnowledgeContext(
            context_kind="entity",
            canonical_entity_id=entity_id,
            label=entity.display_value,
            review_status=entity.review_status,
        )
        session.add(context)
        contexts[entity_id] = context
    session.flush()

    for (source_document_id, entity_id), direct_unit_ids in source_units_by_entity.items():
        context = contexts.get(entity_id)
        if context is None:
            continue
        direct_matches = [
            direct_by_unit[unit_id][entity_id]
            for unit_id in direct_unit_ids
            if entity_id in direct_by_unit[unit_id]
        ]
        direct_confidences = [match.confidence for match in direct_matches if match.confidence is not None]
        inherited_confidence = min(max(direct_confidences, default=0.8), 0.8)
        source_surfaces = sorted({match.surface_text for match in direct_matches})
        for unit_id in unit_ids_by_document[source_document_id]:
            direct_match = direct_by_unit[unit_id].get(entity_id)
            is_direct = direct_match is not None
            session.add(
                KnowledgeContextMembership(
                    context_id=context.id,
                    document_unit_id=unit_id,
                    membership_role="direct" if is_direct else "document_scope",
                    confidence=direct_match.confidence if is_direct else inherited_confidence,
                    source_type="canonical_entity" if is_direct else "same_source_document",
                    evidence_json={
                        "canonical_entity_id": str(entity_id),
                        "matched_surface": direct_match.surface_text if is_direct else None,
                        "source_surfaces": source_surfaces if not is_direct else None,
                    },
                )
            )
    session.flush()
    return context_stats(session)


def context_stats(session: Session) -> ContextProjectionStats:
    return ContextProjectionStats(
        contexts=int(session.execute(select(func.count()).select_from(KnowledgeContext)).scalar_one()),
        memberships=int(
            session.execute(select(func.count()).select_from(KnowledgeContextMembership)).scalar_one()
        ),
    )
