import uuid
from datetime import date
from decimal import Decimal

from api.routers.knowledge import _KnowledgeAgentAction, _agent_search_calendar_events
from common.db.models import CalendarEvent, Document, DocumentType, DocumentUnit, ScanUnit, SpecialistResult


def _add_calendar_event(
    db_session,
    *,
    issuer: str,
    subject: str,
    amount: Decimal,
    due_date: date,
    status: str = "due",
) -> CalendarEvent:
    document = Document(
        original_filename=f"{issuer.lower().replace(' ', '-')}.pdf",
        mime_type="application/pdf",
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        size_bytes=100,
        source_type="upload",
    )
    doc_type = db_session.query(DocumentType).filter(DocumentType.code == "fattura").one_or_none()
    if doc_type is None:
        doc_type = DocumentType(code="fattura", name="Fattura", is_active=True)
        db_session.add(doc_type)
        db_session.flush()
    scan_unit = ScanUnit(
        document=document,
        source_document_id=document.id,
        source_ocr_result_id=uuid.uuid4(),
        page_count=2,
        status="assigned",
    )
    unit = DocumentUnit(
        scan_unit=scan_unit,
        document_type=doc_type,
        document_type_confidence=0.95,
        ordinal=1,
        start_page=1,
        end_page=2,
        title=f"Fattura {issuer}",
        review_status="auto_accepted",
    )
    result = SpecialistResult(
        document_unit=unit,
        specialist_type="utility_bill",
        schema_version="utility_bill_v1",
        confidence=0.9,
        review_status="auto_accepted",
        result_json={"issuer": issuer},
    )
    event = CalendarEvent(
        source_document_unit=unit,
        source_specialist_result=result,
        event_type="payment_due",
        title=f"Bolletta {issuer}",
        subject=subject,
        amount=amount,
        currency="EUR",
        due_date=due_date,
        status=status,
        confidence=0.9,
        review_status="auto_accepted",
        evidence_json={"issuer": issuer, "issues": []},
    )
    db_session.add_all([document, scan_unit, unit, result, event])
    db_session.flush()
    return event


def test_agent_action_accepts_calendar_search_filters():
    action = _KnowledgeAgentAction.model_validate(
        {
            "action": "search_calendar_events",
            "supplier": "acque",
            "date_from": "2024-01-01",
            "date_to": "2024-12-31",
            "amount_min": 50,
            "amount_max": 150,
            "status": "due",
        }
    )

    assert action.action == "search_calendar_events"
    assert action.supplier == "acque"
    assert action.date_from == date(2024, 1, 1)
    assert action.amount_max == 150


def test_agent_calendar_search_filters_supplier_date_and_amount(db_session):
    expected = _add_calendar_event(
        db_session,
        issuer="Acque S.p.A.",
        subject="water · Via Roma",
        amount=Decimal("100.35"),
        due_date=date(2024, 5, 10),
    )
    _add_calendar_event(
        db_session,
        issuer="Enel Energia",
        subject="electricity · Via Roma",
        amount=Decimal("80.00"),
        due_date=date(2024, 5, 20),
    )
    _add_calendar_event(
        db_session,
        issuer="Acque S.p.A.",
        subject="water · Via Milano",
        amount=Decimal("260.00"),
        due_date=date(2024, 6, 10),
    )

    output = _agent_search_calendar_events(
        db_session,
        query=None,
        supplier="acque",
        date_from=date(2024, 5, 1),
        date_to=date(2024, 5, 31),
        amount_min=90,
        amount_max=150,
        status="due",
        review_status=None,
        limit=10,
    )

    assert output["total_returned"] == 1
    assert output["events"][0]["calendar_event_id"] == str(expected.id)
    assert output["events"][0]["supplier"] == "Acque S.p.A."
    assert output["events"][0]["amount"] == 100.35
    assert output["events"][0]["page_from"] == 1
