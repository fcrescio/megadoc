import uuid

from common.application.calendar import project_utility_bill_calendar_event
from common.application.payables import project_payable
from common.db.models import CalendarEvent, Document, DocumentType, DocumentUnit, Payable, ScanUnit, SpecialistResult


def _result(db_session, suffix: str, payload: dict) -> tuple[DocumentUnit, SpecialistResult]:
    document = Document(
        original_filename=f"payable-{suffix}.pdf", mime_type="application/pdf",
        sha256=(suffix * 64)[:64], size_bytes=100, source_type="upload",
    )
    document_type = db_session.query(DocumentType).filter_by(code="fattura").one_or_none()
    if document_type is None:
        document_type = DocumentType(code="fattura", name="Fattura", is_active=True)
    scan = ScanUnit(
        document=document, source_document_id=document.id, source_ocr_result_id=uuid.uuid4(),
        page_count=1, status="assigned",
    )
    unit = DocumentUnit(
        scan_unit=scan, document_type=document_type, document_type_confidence=0.95,
        ordinal=1, start_page=1, end_page=1, review_status="auto_accepted",
    )
    result = SpecialistResult(
        document_unit=unit, specialist_type="utility_bill", schema_version="utility_bill_v1",
        confidence=0.9, review_status="auto_accepted", result_json=payload,
    )
    db_session.add_all([document, document_type, scan, unit, result])
    db_session.flush()
    return unit, result


def test_payable_without_due_date_remains_reviewable(db_session):
    unit, result = _result(db_session, "a", {
        "payable_kind": "invoice", "issuer": "Fornitore S.p.A.",
        "recipient": "Condominio Roma", "total_amount": 120.0,
        "currency": "EUR", "document_number": "FT-10",
    })

    payable = project_payable(db_session, unit, result)
    event = project_utility_bill_calendar_event(db_session, unit, result)

    assert payable is not None
    assert payable.due_date is None
    assert payable.review_status == "needs_review"
    assert "due_date_missing" in payable.evidence_json["issues"]
    assert event is None
    assert db_session.query(Payable).count() == 1


def test_duplicate_payables_create_one_calendar_deadline(db_session):
    payload = {
        "payable_kind": "invoice", "issuer": "Fornitore S.p.A.",
        "recipient": "Condominio Roma", "total_amount": 120.0, "currency": "EUR",
        "due_date": "2026-08-15", "document_number": "FT-10", "payment_status": "unpaid",
    }
    first_unit, first_result = _result(db_session, "b", payload)
    second_unit, second_result = _result(db_session, "c", payload)

    first = project_payable(db_session, first_unit, first_result)
    project_utility_bill_calendar_event(db_session, first_unit, first_result)
    second = project_payable(db_session, second_unit, second_result)
    duplicate_event = project_utility_bill_calendar_event(db_session, second_unit, second_result)

    assert second.duplicate_of_id == first.id
    assert second.review_status == "needs_review"
    assert duplicate_event is None
    assert db_session.query(CalendarEvent).count() == 1


def test_payable_projection_is_idempotent(db_session):
    unit, result = _result(db_session, "d", {
        "payable_kind": "utility_bill", "issuer": "Acque S.p.A.",
        "recipient": "Condominio Roma", "total_amount": 80.0, "currency": "EUR",
        "due_date": "2026-09-01", "payment_reference": "BOL-1",
    })
    first = project_payable(db_session, unit, result)
    second = project_payable(db_session, unit, result)

    assert second.id == first.id
    assert db_session.query(Payable).count() == 1


def test_incomplete_payables_are_not_deduplicated(db_session):
    first_unit, first_result = _result(db_session, "e", {"payable_kind": "invoice"})
    second_unit, second_result = _result(db_session, "f", {"payable_kind": "invoice"})

    first = project_payable(db_session, first_unit, first_result)
    second = project_payable(db_session, second_unit, second_result)

    assert first.duplicate_of_id is None
    assert second.duplicate_of_id is None
