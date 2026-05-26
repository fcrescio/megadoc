from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from common.db.models import (
    CanonicalEntity,
    DocumentUnit,
    KnowledgeContext,
    KnowledgeContextAnchor,
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
    session.execute(delete(KnowledgeContextAnchor))
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
    context_groups = _group_context_entities(eligible_entities, documents_by_entity)
    context_by_entity: dict[uuid.UUID, KnowledgeContext] = {}
    for entity_ids in context_groups:
        primary_entity = min(
            (eligible_entities[entity_id] for entity_id in entity_ids),
            key=_primary_entity_rank,
        )
        context = KnowledgeContext(
            context_kind="entity",
            canonical_entity_id=primary_entity.id,
            label=primary_entity.display_value,
            review_status=primary_entity.review_status,
        )
        session.add(context)
        session.flush()
        for entity_id in entity_ids:
            session.add(
                KnowledgeContextAnchor(
                    context_id=context.id,
                    canonical_entity_id=entity_id,
                    anchor_role="primary" if entity_id == primary_entity.id else "related",
                )
            )
            context_by_entity[entity_id] = context
    session.flush()

    source_units_by_context: dict[tuple[uuid.UUID, uuid.UUID], dict[uuid.UUID, list[_DirectMatch]]] = {}
    contexts_by_id: dict[uuid.UUID, KnowledgeContext] = {}
    for (source_document_id, entity_id), direct_unit_ids in source_units_by_entity.items():
        context = context_by_entity.get(entity_id)
        if context is not None:
            contexts_by_id[context.id] = context
            unit_matches = source_units_by_context.setdefault((source_document_id, context.id), {})
            for unit_id in direct_unit_ids:
                unit_matches.setdefault(unit_id, []).append(direct_by_unit[unit_id][entity_id])

    for (source_document_id, context_id), direct_by_context_unit in source_units_by_context.items():
        context = contexts_by_id[context_id]
        direct_matches = [
            match for matches in direct_by_context_unit.values() for match in matches
        ]
        direct_confidences = [match.confidence for match in direct_matches if match.confidence is not None]
        inherited_confidence = min(max(direct_confidences, default=0.8), 0.8)
        source_surfaces = sorted({match.surface_text for match in direct_matches})
        for unit_id in unit_ids_by_document[source_document_id]:
            unit_matches = direct_by_context_unit.get(unit_id, [])
            is_direct = bool(unit_matches)
            session.add(
                KnowledgeContextMembership(
                    context_id=context.id,
                    document_unit_id=unit_id,
                    membership_role="direct" if is_direct else "document_scope",
                    confidence=max(
                        (match.confidence for match in unit_matches if match.confidence is not None),
                        default=None,
                    ) if is_direct else inherited_confidence,
                    source_type="canonical_entity" if is_direct else "same_source_document",
                    evidence_json={
                        "canonical_entity_ids": sorted(
                            str(entity_id)
                            for entity_id, candidate_context in context_by_entity.items()
                            if candidate_context.id == context_id
                        ),
                        "matched_surfaces": sorted({match.surface_text for match in unit_matches}) if is_direct else None,
                        "source_surfaces": source_surfaces if not is_direct else None,
                    },
                )
            )
    session.flush()
    return context_stats(session)


def _group_context_entities(
    entities: dict[uuid.UUID, CanonicalEntity],
    documents_by_entity: dict[uuid.UUID, set[uuid.UUID]],
) -> list[set[uuid.UUID]]:
    groups: list[set[uuid.UUID]] = []
    for entity in sorted(entities.values(), key=_primary_entity_rank):
        entity_documents = documents_by_entity.get(entity.id, set())
        merged = False
        if len(entity_documents) >= 2:
            for group in groups:
                primary = entities[next(iter(group))]
                primary_documents = documents_by_entity.get(primary.id, set())
                if entity_documents == primary_documents and any(
                    _can_share_context(entities[group_entity_id], entity)
                    for group_entity_id in group
                ):
                    group.add(entity.id)
                    merged = True
                    break
        if not merged:
            groups.append({entity.id})
    return groups


def _can_share_context(left: CanonicalEntity, right: CanonicalEntity) -> bool:
    types = {left.entity_type, right.entity_type}
    return "organizzazione" in types and bool(types & {"indirizzo", "luogo"})


def _primary_entity_rank(entity: CanonicalEntity) -> tuple[int, str]:
    rank = {"organizzazione": 0, "indirizzo": 1, "luogo": 2, "persona": 3}
    return rank.get(entity.entity_type, 4), entity.display_value.lower()


def context_stats(session: Session) -> ContextProjectionStats:
    return ContextProjectionStats(
        contexts=int(session.execute(select(func.count()).select_from(KnowledgeContext)).scalar_one()),
        memberships=int(
            session.execute(select(func.count()).select_from(KnowledgeContextMembership)).scalar_one()
        ),
    )
