"""Tests for pipeline persistence and topic consolidation."""

import uuid

from common.db.models import (
    DocumentType,
    DocumentUnit,
    DocumentUnitEntity,
    DocumentUnitTopicAssignment,
    ScanUnit,
    TopicProposal,
)
from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.schemas import ExtractedEntity
from knowledge_classifier.services.pipeline import KnowledgePipelineService


def test_set_document_type_persists_foreign_key(db_session):
    doc_type = DocumentType(code="preventivo", name="Preventivo", is_active=True)
    scan_unit = ScanUnit(
        source_document_id=uuid.uuid4(),
        source_ocr_result_id=uuid.uuid4(),
        page_count=2,
        status="pending",
    )
    doc_unit = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=1,
        start_page=1,
        end_page=2,
        review_status="auto_accepted",
    )
    db_session.add_all([doc_type, scan_unit, doc_unit])
    db_session.flush()

    service = KnowledgePipelineService(MockDeterministicProvider(), db_session)
    service._set_document_type(doc_unit, "preventivo")
    db_session.flush()

    assert doc_unit.document_type_id == doc_type.id
    assert service._get_document_type_code(doc_unit) == "preventivo"


def test_normalize_entities_offsets_pages_and_deduplicates(db_session):
    service = KnowledgePipelineService(MockDeterministicProvider(), db_session)
    entities = [
        ExtractedEntity(
            entity_type="persona",
            entity_value="BERTI Patrizia",
            normalized_value=None,
            confidence=0.9,
            page_from=1,
            page_to=1,
        ),
        ExtractedEntity(
            entity_type="persona",
            entity_value="BERTI Patrizia",
            normalized_value=None,
            confidence=0.9,
            page_from=1,
            page_to=1,
        ),
        ExtractedEntity(
            entity_type="data",
            entity_value="2025-11-15",
            normalized_value=None,
            confidence=0.9,
            page_from=2,
            page_to=2,
        ),
    ]

    normalized = service._normalize_entities(entities, start_page=4, end_page=9)

    assert len(normalized) == 2
    assert normalized[0].page_from == 4
    assert normalized[0].page_to == 4
    assert normalized[0].normalized_value == "berti_patrizia"
    assert normalized[1].page_from == 5
    assert normalized[1].page_to == 5


def test_create_topic_proposal_reuses_existing_provisional_topic_in_same_scan(db_session):
    scan_unit = ScanUnit(
        source_document_id=uuid.uuid4(),
        source_ocr_result_id=uuid.uuid4(),
        page_count=6,
        status="processing",
    )
    doc_unit_1 = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=1,
        start_page=1,
        end_page=3,
        review_status="auto_accepted",
    )
    doc_unit_2 = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=2,
        start_page=4,
        end_page=6,
        review_status="auto_accepted",
    )
    db_session.add_all([scan_unit, doc_unit_1, doc_unit_2])
    db_session.flush()

    service = KnowledgePipelineService(MockDeterministicProvider(), db_session)

    first_decision = type(
        "Decision",
        (),
        {
            "proposed_topic": {
                "proposed_slug": "condominio_via_burchietti_37_39_scandicci",
                "proposed_title": "Condominio Via Burchietti 37/39 - Scandicci",
                "topic_class": "case_file",
                "description": "Documenti del condominio",
            },
            "confidence": 0.92,
            "rationale": "First proposal",
        },
    )()
    second_decision = type(
        "Decision",
        (),
        {
            "proposed_topic": {
                "proposed_slug": "condominio_via_burchietti_bilancio_2025_2026",
                "proposed_title": "Condominio Via Burchietti - Bilancio Preventivo 2025/2026",
                "topic_class": "financial_period",
                "description": "Budget documents",
            },
            "confidence": 0.91,
            "rationale": "Second proposal",
        },
    )()
    entities = [
        ExtractedEntity(
            entity_type="condominio",
            entity_value="Condominio Via Burchietti 37/39 - Scandicci",
            normalized_value="condominio_via_burchietti_37_39_scandicci",
            confidence=0.95,
            page_from=1,
            page_to=1,
        )
    ]

    service._create_topic_proposal(scan_unit, doc_unit_1, first_decision, entities)
    db_session.flush()

    reused = service._find_reusable_topic_proposal(scan_unit, second_decision, entities)

    assert reused is not None
    assert reused.source_document_unit_id == doc_unit_1.id
    assert reused.matched_existing_topic_id is not None

    reused_topic_id = reused.matched_existing_topic_id
    service._create_topic_assignments(
        doc_unit_2,
        type(
            "AssignmentDecision",
            (),
            {
                "topic_ids": [str(reused_topic_id)],
                "assignment_roles": ["primary"],
                "confidence": 0.91,
                "rationale": "Reuse same provisional topic",
            },
        )(),
    )
    db_session.flush()

    proposals = db_session.query(TopicProposal).all()
    assignments = (
        db_session.query(DocumentUnitTopicAssignment)
        .order_by(DocumentUnitTopicAssignment.document_unit_id)
        .all()
    )
    entities_count = db_session.query(DocumentUnitEntity).count()

    assert len(proposals) == 1
    assert len(assignments) == 2
    assert assignments[0].topic_id == assignments[1].topic_id == reused_topic_id
    assert entities_count == 0
