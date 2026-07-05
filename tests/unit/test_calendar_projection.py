import uuid

from common.application.calendar import project_utility_bill_calendar_event
from common.db.models import CalendarEvent, Document, DocumentType, DocumentUnit, ScanUnit, SpecialistResult


def _make_utility_result(db_session, result_json: dict, confidence: float = 0.9) -> tuple[DocumentUnit, SpecialistResult]:
    document = Document(
        original_filename="bolletta.pdf",
        mime_type="application/pdf",
        sha256="b" * 64,
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
    result = SpecialistResult(
        document_unit=unit,
        specialist_type="utility_bill",
        schema_version="utility_bill_v1",
        confidence=confidence,
        review_status="auto_accepted",
        result_json=result_json,
    )
    db_session.add_all([document, doc_type, scan_unit, unit, result])
    db_session.flush()
    return unit, result


def test_projects_valid_utility_bill_due_event(db_session):
    unit, result = _make_utility_result(
        db_session,
        {
            "issuer": "Acque S.p.A.",
            "service_type": "water",
            "supply_reference": "VIA ROMA 1",
            "account_holder": "Condominio Via Roma",
            "due_date": "2024-04-20",
            "total_amount": 128.4,
            "currency": "EUR",
            "payment_status": "unpaid",
        },
    )

    event = project_utility_bill_calendar_event(db_session, unit, result)
    db_session.flush()

    assert event is not None
    assert db_session.query(CalendarEvent).count() == 1
    assert event.status == "due"
    assert event.review_status == "auto_accepted"
    assert str(event.amount) == "128.40"
    assert event.subject == "water · VIA ROMA 1 · Condominio Via Roma"


def test_projects_due_event_but_flags_out_of_range_amount(db_session):
    unit, result = _make_utility_result(
        db_session,
        {
            "issuer": "Enel",
            "due_date": "2024-05-10",
            "total_amount": 10000000,
            "currency": "EUR",
            "payment_status": "unknown",
        },
    )

    event = project_utility_bill_calendar_event(db_session, unit, result)
    db_session.flush()

    assert event is not None
    assert event.amount is None
    assert event.status == "unknown"
    assert event.review_status == "needs_review"
    assert event.evidence_json["issues"] == ["amount_missing_or_out_of_range", "payment_status_unknown"]
