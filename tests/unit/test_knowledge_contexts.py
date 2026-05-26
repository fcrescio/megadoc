import uuid

from api.routers.knowledge import (
    get_knowledge_context,
    list_knowledge_contexts,
    rebuild_context_projection,
)
from common.application.contexts import rebuild_knowledge_contexts
from common.db.models import (
    CanonicalEntity,
    CanonicalEntityVariant,
    Document,
    DocumentUnit,
    DocumentUnitEntity,
    KnowledgeContext,
    KnowledgeContextAnchor,
    KnowledgeContextMembership,
    ScanUnit,
)


def _make_document_units(db_session, filename: str, entities_by_unit: list[list[DocumentUnitEntity]]) -> list[DocumentUnit]:
    document = Document(
        original_filename=filename,
        mime_type="application/pdf",
        sha256=(filename.encode().hex() + ("0" * 64))[:64],
        size_bytes=100,
        source_type="upload",
    )
    scan_unit = ScanUnit(
        document=document,
        source_document_id=document.id,
        source_ocr_result_id=uuid.uuid4(),
        page_count=len(entities_by_unit),
        status="assigned",
    )
    units = []
    for index, entities in enumerate(entities_by_unit, start=1):
        unit = DocumentUnit(
            scan_unit=scan_unit,
            ordinal=index,
            start_page=index,
            end_page=index,
            title=f"Segmento {index}",
            review_status="auto_accepted",
        )
        unit.entities.extend(entities)
        units.append(unit)
    db_session.add_all([document, scan_unit, *units])
    db_session.flush()
    return units


def _entity(value: str, key: str, confidence: float = 0.92) -> DocumentUnitEntity:
    return DocumentUnitEntity(
        entity_type="organizzazione",
        entity_value=value,
        normalized_value=key,
        confidence=confidence,
        page_from=1,
        page_to=1,
    )


def test_context_projection_groups_variants_and_propagates_document_scope(db_session):
    canonical = CanonicalEntity(
        entity_type="organizzazione",
        canonical_value="condominio_cesare_studiati_pisa",
        display_value="Condominio Cesare Studiati, Pisa",
        review_status="human_reviewed",
    )
    canonical.variants.extend(
        [
            CanonicalEntityVariant(
                entity_type="organizzazione",
                entity_key="condominio_studiati_6_10a_via",
                display_value="CONDOMINIO STUDIATI 6/10A (VIA)",
                review_status="human_reviewed",
            ),
            CanonicalEntityVariant(
                entity_type="organizzazione",
                entity_key="condominio_cesare_studiati_6_10a",
                display_value="Condominio Cesare Studiati 6-10/A",
                review_status="human_reviewed",
            ),
        ]
    )
    address = CanonicalEntity(
        entity_type="indirizzo",
        canonical_value="via_cesare_studiati_6_10a_pisa",
        display_value="Via Cesare Studiati 6-10/A, Pisa",
        review_status="human_reviewed",
    )
    address.variants.append(
        CanonicalEntityVariant(
            entity_type="indirizzo",
            entity_key="via_cesare_studiati_6_10a",
            display_value="Via Cesare Studiati 6-10/A",
            review_status="human_reviewed",
        )
    )
    db_session.add_all([canonical, address])
    first_units = _make_document_units(
        db_session,
        "allegato-contabile.pdf",
        [
            [
                _entity("CONDOMINIO STUDIATI 6/10A (VIA)", "condominio_studiati_6_10a_via"),
                DocumentUnitEntity(
                    entity_type="indirizzo",
                    entity_value="Via Cesare Studiati 6-10/A",
                    normalized_value="via_cesare_studiati_6_10a",
                    confidence=0.9,
                ),
            ],
            [_entity("Studio Amministratore", "studio_amministratore", confidence=0.7)],
        ],
    )
    second_units = _make_document_units(
        db_session,
        "estratto-conto.pdf",
        [[
            _entity("Condominio Cesare Studiati 6-10/A", "condominio_cesare_studiati_6_10a"),
            DocumentUnitEntity(
                entity_type="indirizzo",
                entity_value="Via Cesare Studiati 6-10/A",
                normalized_value="via_cesare_studiati_6_10a",
                confidence=0.9,
            ),
        ]],
    )

    stats = rebuild_knowledge_contexts(db_session)

    assert stats.contexts == 1
    assert stats.memberships == 3
    context = db_session.query(KnowledgeContext).one()
    assert context.canonical_entity_id == canonical.id
    assert db_session.query(KnowledgeContextAnchor).count() == 2
    memberships = {
        membership.document_unit_id: membership
        for membership in db_session.query(KnowledgeContextMembership).all()
    }
    assert memberships[first_units[0].id].membership_role == "direct"
    assert memberships[first_units[1].id].membership_role == "document_scope"
    assert memberships[first_units[1].id].source_type == "same_source_document"
    assert memberships[second_units[0].id].membership_role == "direct"

    rebuilt = rebuild_knowledge_contexts(db_session)
    assert rebuilt == stats
    assert db_session.query(KnowledgeContext).one().id == context.id


def test_context_projection_requires_review_or_cross_document_repetition(db_session):
    canonical = CanonicalEntity(
        entity_type="organizzazione",
        canonical_value="azienda_ricorrente",
        display_value="Azienda Ricorrente",
        review_status="auto",
    )
    canonical.variants.append(
        CanonicalEntityVariant(
            entity_type="organizzazione",
            entity_key="azienda_ricorrente",
            display_value="Azienda Ricorrente",
            review_status="auto",
        )
    )
    db_session.add(canonical)
    _make_document_units(db_session, "prima-lettera.pdf", [[_entity("Azienda Ricorrente", "azienda_ricorrente")]])

    assert rebuild_knowledge_contexts(db_session).contexts == 0

    _make_document_units(db_session, "seconda-lettera.pdf", [[_entity("Azienda Ricorrente", "azienda_ricorrente")]])
    stats = rebuild_knowledge_contexts(db_session)
    assert stats.contexts == 1
    assert stats.memberships == 2


def test_context_api_rebuild_lists_and_opens_membership_evidence(db_session):
    canonical = CanonicalEntity(
        entity_type="organizzazione",
        canonical_value="condominio_via_roma",
        display_value="Condominio Via Roma",
        review_status="human_reviewed",
    )
    canonical.variants.append(
        CanonicalEntityVariant(
            entity_type="organizzazione",
            entity_key="condominio_via_roma",
            display_value="Condominio Via Roma",
            review_status="human_reviewed",
        )
    )
    db_session.add(canonical)
    _make_document_units(db_session, "verbale.pdf", [[_entity("Condominio Via Roma", "condominio_via_roma")]])
    db_session.commit()

    stats = rebuild_context_projection(db_session)
    assert stats.contexts == 1

    contexts = list_knowledge_contexts(q="Via Roma", entity_type="organizzazione", limit=30, db=db_session)
    assert contexts[0].document_count == 1
    detail = get_knowledge_context(uuid.UUID(contexts[0].id), db=db_session)
    assert detail.context.label == "Condominio Via Roma"
    assert detail.memberships[0].document.original_filename == "verbale.pdf"
    assert detail.memberships[0].source_type == "canonical_entity"
