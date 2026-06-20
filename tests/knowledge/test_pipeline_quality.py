"""Tests for pipeline persistence and topic consolidation."""

import uuid
from types import SimpleNamespace

from common.db.models import (
    DocumentType,
    DocumentUnit,
    DocumentUnitEntity,
    DocumentUnitTopicAssignment,
    ScanUnit,
    Topic,
    TopicProposal,
)
from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.schemas import ExtractedEntity, TopicCandidate
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
            entity_type="luogo",
            entity_value="Scandicci",
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
            "proposal_action": "create_topic",
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
            "proposal_action": "create_topic",
            "confidence": 0.91,
            "rationale": "Second proposal",
        },
    )()
    entities = [
        ExtractedEntity(
            entity_type="organizzazione",
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


def test_create_topic_assignments_resolves_malformed_reference_to_single_strong_candidate(
    db_session,
):
    scan_unit = ScanUnit(
        source_document_id=uuid.uuid4(),
        source_ocr_result_id=uuid.uuid4(),
        page_count=1,
        status="processing",
    )
    doc_unit = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=1,
        start_page=1,
        end_page=1,
        review_status="auto_accepted",
    )
    topic = Topic(
        slug="contabilita-condominio-cesare-studiati-pisa",
        title="Contabilita Condominio Cesare Studiati Pisa",
        topic_class="financial_period",
        topic_kind="family",
        canonical=True,
        is_active=True,
    )
    db_session.add_all([scan_unit, doc_unit, topic])
    db_session.flush()

    service = KnowledgePipelineService(MockDeterministicProvider(), db_session)
    decision = SimpleNamespace(
        topic_ids=["contabilita-condominio-cesare-studiati-pisa"],
        assignment_roles=["primary"],
        confidence=0.93,
        rationale="Same condominium accounting archive.",
    )
    candidate = TopicCandidate(
        topic_id=str(topic.id),
        slug=topic.slug,
        title=topic.title,
        score=0.95,
        reasons=["Address match"],
    )

    service._create_topic_assignments(doc_unit, decision, [candidate])
    db_session.flush()

    assignment = db_session.query(DocumentUnitTopicAssignment).one()
    assert assignment.topic_id == topic.id


def test_looks_like_condominium_regulation_detects_fragmented_regulation_scan(db_session):
    contract_type = DocumentType(code="contratto", name="Contratto", is_active=True)
    meeting_type = DocumentType(code="verbale_assemblea", name="Verbale assemblea", is_active=True)
    scan_unit = ScanUnit(
        source_document_id=uuid.uuid4(),
        source_ocr_result_id=uuid.uuid4(),
        page_count=12,
        status="processing",
    )
    doc_units = [
        DocumentUnit(
            scan_unit=scan_unit,
            ordinal=1,
            start_page=1,
            end_page=5,
            review_status="needs_review",
            extracted_summary="Regolamento del condominio con articoli e norme sulle spese comuni.",
            document_type=contract_type,
            document_type_confidence=0.91,
        ),
        DocumentUnit(
            scan_unit=scan_unit,
            ordinal=2,
            start_page=6,
            end_page=8,
            review_status="needs_review",
            extracted_summary="Norme assembleari e convocazioni previste dal regolamento.",
            document_type=meeting_type,
            document_type_confidence=0.88,
        ),
    ]
    db_session.add_all([contract_type, meeting_type, scan_unit, *doc_units])
    db_session.flush()

    service = KnowledgePipelineService(MockDeterministicProvider(), db_session)
    scan_text = (
        "Regolamento del condominio. Art. 1 proprieta comune. "
        "Art. 2 assemblea. Articolo 3 ripartizione spese. Articolo 4 amministratore."
    )

    assert service._looks_like_condominium_regulation(scan_text.lower(), doc_units) is True


def test_pick_regulation_canonical_unit_prefers_condominium_anchor(db_session):
    scan_unit = ScanUnit(
        source_document_id=uuid.uuid4(),
        source_ocr_result_id=uuid.uuid4(),
        page_count=8,
        status="processing",
    )
    doc_unit_1 = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=1,
        start_page=1,
        end_page=3,
        review_status="needs_review",
        extracted_summary="Regolamento generale delle parti comuni.",
    )
    doc_unit_2 = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=2,
        start_page=4,
        end_page=8,
        review_status="needs_review",
        extracted_summary="Regolamento del condominio di Via Cesare Studiati.",
    )
    db_session.add_all([scan_unit, doc_unit_1, doc_unit_2])
    db_session.flush()

    service = KnowledgePipelineService(MockDeterministicProvider(), db_session)
    entity_results = {
        doc_unit_1.id: SimpleNamespace(entities=[]),
        doc_unit_2.id: SimpleNamespace(
            entities=[
                ExtractedEntity(
                    entity_type="organizzazione",
                    entity_value="Condominio Via Cesare Studiati",
                    normalized_value="condominio_via_cesare_studiati",
                    confidence=0.95,
                    page_from=4,
                    page_to=4,
                )
            ]
        ),
    }

    canonical = service._pick_regulation_canonical_unit([doc_unit_1, doc_unit_2], entity_results)

    assert canonical is not None
    assert canonical.id == doc_unit_2.id


def test_consolidate_financial_topics_merges_same_vendor_proposals(db_session):
    scan_unit = ScanUnit(
        source_document_id=uuid.uuid4(),
        source_ocr_result_id=uuid.uuid4(),
        page_count=2,
        status="processing",
    )
    fattura_type = DocumentType(code="fattura", name="Fattura", is_active=True)
    doc_unit_1 = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=1,
        start_page=1,
        end_page=1,
        review_status="needs_review",
        document_type=fattura_type,
    )
    doc_unit_2 = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=2,
        start_page=2,
        end_page=2,
        review_status="needs_review",
        document_type=fattura_type,
    )
    db_session.add_all([scan_unit, fattura_type, doc_unit_1, doc_unit_2])
    db_session.flush()

    service = KnowledgePipelineService(MockDeterministicProvider(), db_session)
    entities_1 = [
        ExtractedEntity(
            entity_type="organizzazione",
            entity_value="Elettrosat snc",
            normalized_value="elettrosat_snc",
            confidence=0.95,
            page_from=1,
            page_to=1,
        )
    ]
    entities_2 = [
        ExtractedEntity(
            entity_type="organizzazione",
            entity_value="Elettrosat snc",
            normalized_value="elettrosat_snc",
            confidence=0.95,
            page_from=2,
            page_to=2,
        )
    ]
    first_decision = type(
        "Decision",
        (),
        {
            "proposed_topic": {
                "proposed_slug": "invoice_from_elettrosat_snc",
                "proposed_title": "Invoice from Elettrosat snc",
                "topic_class": "vendor_relationship",
                "description": "Invoices from Elettrosat",
            },
            "proposal_action": "create_topic",
            "confidence": 0.91,
            "rationale": "First invoice",
        },
    )()
    second_decision = type(
        "Decision",
        (),
        {
            "proposed_topic": {
                "proposed_slug": "invoice_from_elettrosat_snc_april_2007",
                "proposed_title": "Invoice from Elettrosat snc - April 2007",
                "topic_class": "vendor_relationship",
                "description": "Another invoice from same vendor",
            },
            "proposal_action": "create_topic",
            "confidence": 0.9,
            "rationale": "Second invoice",
        },
    )()

    service._create_topic_proposal(scan_unit, doc_unit_1, first_decision, entities_1)
    service._create_topic_proposal(scan_unit, doc_unit_2, second_decision, entities_2)
    db_session.flush()

    service._consolidate_financial_topics(
        scan_unit,
        [doc_unit_1, doc_unit_2],
        {
            doc_unit_1.id: SimpleNamespace(entities=entities_1),
            doc_unit_2.id: SimpleNamespace(entities=entities_2),
        },
    )
    db_session.flush()

    proposals = db_session.query(TopicProposal).all()
    assignments = (
        db_session.query(DocumentUnitTopicAssignment)
        .order_by(DocumentUnitTopicAssignment.document_unit_id)
        .all()
    )

    assert len(proposals) == 1
    assert len(assignments) == 2
    assert assignments[0].topic_id == assignments[1].topic_id


def test_attach_to_context_proposal_creates_reviewable_proposal(db_session):
    """attach_to_context must produce a TopicProposal with recommended_action and a non-null matched_existing_topic_id."""
    scan_unit = ScanUnit(
        source_document_id=uuid.uuid4(),
        source_ocr_result_id=uuid.uuid4(),
        page_count=2,
        status="processing",
    )
    doc_unit = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=1,
        start_page=1,
        end_page=2,
        review_status="auto_accepted",
        title="Fattura Elettrosat marzo 2007",
    )
    db_session.add_all([scan_unit, doc_unit])
    db_session.flush()

    service = KnowledgePipelineService(MockDeterministicProvider(), db_session)

    # Simulate the decision that _assign_topics builds when proposal_action == "attach_to_context"
    # and decision.proposed_topic is None (the inline fallback at pipeline.py:646-655).
    decision = type(
        "Decision",
        (),
        {
            "proposed_topic": {
                "proposed_slug": f"attach-to-context-{doc_unit.id.hex[:8]}",
                "proposed_title": f"Allega a contesto: {doc_unit.title[:80]}",
                "topic_class": "other",
                "topic_kind": "context",
                "description": "Documento ripetitivo/routine da agganciare a contesto esistente senza creare topic canonico.",
            },
            "proposal_action": "attach_to_context",
            "confidence": 0.85,
            "rationale": "Documento ripetitivo dello stesso fornitore, da agganciare al contesto esistente.",
        },
    )()
    entities = [
        ExtractedEntity(
            entity_type="organizzazione",
            entity_value="Elettrosat snc",
            normalized_value="elettrosat_snc",
            confidence=0.95,
            page_from=1,
            page_to=1,
        )
    ]

    service._create_topic_proposal(scan_unit, doc_unit, decision, entities)
    db_session.flush()

    proposals = db_session.query(TopicProposal).all()
    assert len(proposals) == 1

    proposal = proposals[0]
    assert proposal.proposed_title.startswith("Allega a contesto:")
    assert proposal.matched_existing_topic_id is not None
    assert proposal.review_payload_json is not None
    assert proposal.review_payload_json.get("recommended_action") == "attach_to_context"
    assert proposal.proposal_status == "proposed"

    # Verify the provisional topic was created
    topic = db_session.query(Topic).filter(Topic.id == proposal.matched_existing_topic_id).one()
    assert topic.canonical is False
    assert topic.is_active is False
    assert topic.topic_kind == "context"

    # Verify the assignment was created
    assignment = (
        db_session.query(DocumentUnitTopicAssignment)
        .filter(DocumentUnitTopicAssignment.document_unit_id == doc_unit.id)
        .one()
    )
    assert assignment.topic_id == topic.id
    assert assignment.assignment_role == "person_or_org_context"

    # Verify doc_unit is marked for review
    assert doc_unit.review_status == "needs_review"


def test_ensure_attach_context_proposed_topic_fallback_when_missing(db_session):
    """_ensure_attach_context_proposed_topic must build a minimal proposed_topic when it is None."""
    doc_unit = DocumentUnit(
        scan_unit=ScanUnit(
            source_document_id=uuid.uuid4(),
            source_ocr_result_id=uuid.uuid4(),
            page_count=1,
            status="processing",
        ),
        ordinal=1,
        start_page=1,
        end_page=1,
        review_status="auto_accepted",
        title="Fattura Elettrosat marzo 2007",
    )
    db_session.add(doc_unit)
    db_session.flush()

    decision = type(
        "Decision",
        (),
        {
            "proposed_topic": None,
            "proposal_action": "attach_to_context",
            "confidence": 0.85,
            "rationale": "Documento ripetitivo.",
        },
    )()

    KnowledgePipelineService._ensure_attach_context_proposed_topic(decision, doc_unit)

    assert decision.proposed_topic is not None
    assert decision.proposed_topic["proposed_slug"] == f"attach-to-context-{doc_unit.id.hex[:8]}"
    assert decision.proposed_topic["proposed_title"] == "Allega a contesto: Fattura Elettrosat marzo 2007"
    assert decision.proposed_topic["topic_class"] == "other"
    assert decision.proposed_topic["topic_kind"] == "context"


def test_ensure_attach_context_proposed_topic_does_not_overwrite_existing(db_session):
    """_ensure_attach_context_proposed_topic must not overwrite an existing proposed_topic."""
    doc_unit = DocumentUnit(
        scan_unit=ScanUnit(
            source_document_id=uuid.uuid4(),
            source_ocr_result_id=uuid.uuid4(),
            page_count=1,
            status="processing",
        ),
        ordinal=1,
        start_page=1,
        end_page=1,
        review_status="auto_accepted",
        title="Fattura Elettrosat marzo 2007",
    )
    db_session.add(doc_unit)
    db_session.flush()

    existing_topic = {"proposed_slug": "custom-slug", "proposed_title": "Custom Title", "topic_class": "vendor_relationship"}
    decision = type(
        "Decision",
        (),
        {
            "proposed_topic": existing_topic,
            "proposal_action": "attach_to_context",
            "confidence": 0.85,
            "rationale": "Documento ripetitivo.",
        },
    )()

    KnowledgePipelineService._ensure_attach_context_proposed_topic(decision, doc_unit)

    assert decision.proposed_topic is existing_topic
    assert decision.proposed_topic["proposed_slug"] == "custom-slug"
