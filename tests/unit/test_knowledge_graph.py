import uuid

from api.routers.knowledge import get_knowledge_node, list_knowledge_nodes, rebuild_graph_projection
from common.application.graph import graph_stats, project_document_unit, rebuild_knowledge_graph
from common.db.models import (
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
