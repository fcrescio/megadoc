import uuid

from api.routers.knowledge import get_knowledge_node, list_knowledge_nodes, rebuild_graph_projection
from common.application.graph import graph_stats, project_document_unit, rebuild_knowledge_graph
from common.db.models import (
    CanonicalEntity,
    CanonicalEntityVariant,
    Document,
    DocumentType,
    DocumentUnit,
    DocumentUnitEntity,
    KnowledgeAssertion,
    KnowledgeNode,
    ScanUnit,
    SpecialistResult,
)


def _make_utility_unit(db_session) -> DocumentUnit:
    document = Document(
        original_filename="bolletta-acqua.pdf",
        mime_type="application/pdf",
        sha256="a" * 64,
        size_bytes=100,
        source_type="upload",
    )
    doc_type = DocumentType(code="bolletta", name="Bolletta", is_active=True)
    scan_unit = ScanUnit(
        document=document,
        source_document_id=document.id,
        source_ocr_result_id=uuid.uuid4(),
        page_count=1,
        status="assigned",
    )
    unit = DocumentUnit(
        scan_unit=scan_unit,
        document_type=doc_type,
        document_type_confidence=0.95,
        ordinal=1,
        start_page=1,
        end_page=1,
        review_status="auto_accepted",
    )
    unit.entities.extend(
        [
            DocumentUnitEntity(
                entity_type="organizzazione",
                entity_value="Condominio Via Roma",
                normalized_value="condominio_via_roma",
                confidence=0.94,
                page_from=1,
                page_to=1,
            ),
            DocumentUnitEntity(
                entity_type="organizzazione",
                entity_value="Acque S.p.A.",
                normalized_value="acque_spa",
                confidence=0.91,
                page_from=1,
                page_to=1,
            ),
        ]
    )
    unit.specialist_results.append(
        SpecialistResult(
            specialist_type="utility_bill",
            schema_version="utility_bill_v1",
            confidence=0.92,
            review_status="auto_accepted",
            result_json={
                "issuer": "Acque S.p.A.",
                "service_type": "water",
                "due_date": "2024-04-20",
                "billing_period_from": "2024-03-01",
                "billing_period_to": "2024-03-31",
                "total_amount": 128.4,
                "currency": "EUR",
                "payment_status": "unpaid",
            },
        )
    )
    db_session.add_all([document, doc_type, scan_unit, unit])
    db_session.flush()
    return unit


def test_projection_creates_nodes_mentions_and_typed_assertions(db_session):
    unit = _make_utility_unit(db_session)

    project_document_unit(db_session, unit)
    db_session.flush()

    nodes = db_session.query(KnowledgeNode).all()
    assertions = db_session.query(KnowledgeAssertion).all()
    assert {node.label for node in nodes} == {"Condominio Via Roma", "Acque S.p.A."}
    assert graph_stats(db_session).mentions == 2
    assert {item.predicate_code for item in assertions} >= {
        "about",
        "issued_by",
        "due_date",
        "covers_period",
        "amount_total",
        "payment_status",
    }
    amount = next(item for item in assertions if item.predicate_code == "amount_total")
    assert amount.value_json == {"amount": 128.4, "currency": "EUR"}


def test_rebuild_graph_is_idempotent(db_session):
    _make_utility_unit(db_session)

    first = rebuild_knowledge_graph(db_session)
    second = rebuild_knowledge_graph(db_session)

    assert first.nodes == second.nodes == 2
    assert first.mentions == second.mentions == 2
    assert first.assertions == second.assertions


def test_graph_api_rebuild_and_browse_node(db_session):
    _make_utility_unit(db_session)
    db_session.commit()

    rebuilt = rebuild_graph_projection(db_session)
    assert rebuilt.nodes == 2

    nodes = list_knowledge_nodes(q="Condominio", node_kind=None, limit=30, db=db_session)
    node_id = uuid.UUID(nodes[0].id)

    detail = get_knowledge_node(node_id, db=db_session)
    assert detail.node.label == "Condominio Via Roma"
    assert detail.documents[0].original_filename == "bolletta-acqua.pdf"
    assert {assertion.predicate_code for assertion in detail.assertions} >= {"about", "due_date", "amount_total"}


def test_projection_uses_display_text_instead_of_inconsistent_extracted_keys(db_session):
    unit = _make_utility_unit(db_session)
    unit.entities.append(
        DocumentUnitEntity(
            entity_type="organizzazione",
            entity_value="Condominio Via Roma",
            normalized_value="condominio_via__roma_v2",
            confidence=0.8,
            page_from=1,
            page_to=1,
        )
    )

    project_document_unit(db_session, unit)

    condominium_nodes = db_session.query(KnowledgeNode).filter_by(node_kind="organization").all()
    assert [node.label for node in condominium_nodes if node.label == "Condominio Via Roma"] == [
        "Condominio Via Roma"
    ]


def test_projection_respects_reviewed_canonical_entity_variants(db_session):
    unit = _make_utility_unit(db_session)
    canonical = CanonicalEntity(
        entity_type="organizzazione",
        canonical_value="condominio_studiati",
        display_value="Condominio Studiati",
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
    db_session.flush()

    project_document_unit(db_session, unit)

    node = db_session.query(KnowledgeNode).filter_by(canonical_key="condominio_studiati").one()
    assert node.label == "Condominio Studiati"
    assert node.review_status == "human_reviewed"
    assert {alias.alias for alias in node.aliases} >= {"Condominio Studiati", "Condominio Via Roma"}


def test_accounting_projection_does_not_promote_allocation_people_to_nodes(db_session):
    unit = _make_utility_unit(db_session)
    unit.entities.append(
        DocumentUnitEntity(
            entity_type="persona",
            entity_value="Rossi Mario / Bianchi Lucia",
            normalized_value="rossi_mario_bianchi_lucia",
            confidence=0.7,
            page_from=1,
            page_to=1,
        )
    )
    unit.specialist_results.append(
        SpecialistResult(
            specialist_type="accounting_statement",
            schema_version="accounting_v1",
            confidence=0.91,
            review_status="auto_accepted",
            result_json={"statement_type": "riparto"},
        )
    )

    project_document_unit(db_session, unit)

    assert db_session.query(KnowledgeNode).filter_by(node_kind="person").count() == 0


def test_projection_excludes_malformed_table_content_from_navigation(db_session):
    unit = _make_utility_unit(db_session)
    table_payload = "<table><tr><td>" + ("Acque Spa - Fattura " * 60) + "</td></tr></table>"
    unit.entities.append(
        DocumentUnitEntity(
            entity_type="organizzazione",
            entity_value=table_payload,
            normalized_value="malformed_table",
            confidence=0.3,
            page_from=1,
            page_to=1,
        )
    )
    utility_result = unit.specialist_results[0]
    utility_result.result_json = {
        **utility_result.result_json,
        "issuer": table_payload,
        "service_type": table_payload,
    }

    project_document_unit(db_session, unit)

    assertions = db_session.query(KnowledgeAssertion).all()
    assert graph_stats(db_session).mentions == 2
    assert not any("<table" in node.label for node in db_session.query(KnowledgeNode).all())
    assert not any(assertion.source_type == "utility_bill" for assertion in assertions)
