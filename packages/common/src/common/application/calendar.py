from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import CalendarEvent, DocumentUnit, Payable, SpecialistResult

MAX_AUTO_ACCEPTED_UTILITY_AMOUNT = Decimal("5000.00")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _parse_amount(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if amount < 0 or amount > MAX_AUTO_ACCEPTED_UTILITY_AMOUNT:
        return None
    return amount.quantize(Decimal("0.01"))


def _calendar_status(payment_status: Any) -> str:
    if payment_status == "paid":
        return "paid"
    if payment_status == "unpaid":
        return "due"
    return "unknown"


def project_utility_bill_calendar_event(
    session: Session,
    document_unit: DocumentUnit,
    specialist_result: SpecialistResult,
) -> CalendarEvent | None:
    """Project a utility bill extraction into a reviewable calendar due event."""

    if specialist_result.specialist_type != "utility_bill":
        return None
    payload = specialist_result.result_json or {}
    payable = session.execute(
        select(Payable).where(Payable.source_specialist_result_id == specialist_result.id)
    ).scalar_one_or_none()
    due_date = _parse_date(payload.get("due_date"))
    existing = session.execute(
        select(CalendarEvent).where(
            CalendarEvent.source_specialist_result_id == specialist_result.id,
            CalendarEvent.event_type == "payment_due",
        )
    ).scalar_one_or_none()
    if due_date is None or (payable is not None and payable.duplicate_of_id is not None):
        if existing is not None:
            session.delete(existing)
        return None

    issuer = str(payload.get("issuer") or "utenza").strip()
    service_type = str(payload.get("service_type") or "").strip()
    supply_reference = str(payload.get("supply_reference") or "").strip()
    account_holder = str(payload.get("account_holder") or "").strip()
    subject_parts = [part for part in (service_type, supply_reference, account_holder) if part]
    subject = " · ".join(subject_parts) or None

    raw_amount = payload.get("total_amount")
    amount = _parse_amount(raw_amount)
    issues: list[str] = []
    if amount is None:
        issues.append("amount_missing_or_out_of_range")
    if payload.get("payment_status") not in {"paid", "unpaid"}:
        issues.append("payment_status_unknown")

    confidence = specialist_result.confidence
    if issues and confidence is not None:
        confidence = max(0.0, confidence - 0.2)
    review_status = "auto_accepted" if not issues and (confidence is None or confidence >= 0.7) else "needs_review"

    event = existing or CalendarEvent(
        source_document_unit_id=document_unit.id,
        source_specialist_result_id=specialist_result.id,
        event_type="payment_due",
    )
    event.source_document_unit_id = document_unit.id
    kind_label = {
        "invoice": "Fattura",
        "payment_notice": "Avviso",
        "reminder": "Sollecito",
        "receipt": "Quietanza",
    }.get(str(payload.get("payable_kind") or ""), "Bolletta")
    event.title = f"{kind_label} {issuer} - scadenza {due_date.isoformat()}"
    event.subject = subject
    event.amount = amount
    event.currency = str(payload.get("currency") or "EUR").strip()[:8] or "EUR"
    event.due_date = due_date
    event.status = _calendar_status(payload.get("payment_status"))
    event.confidence = confidence
    event.review_status = review_status
    event.evidence_json = {
        "source": "utility_bill_specialist",
        "payable_id": str(payable.id) if payable is not None else None,
        "issuer": payload.get("issuer"),
        "raw_total_amount": raw_amount,
        "raw_due_date": payload.get("due_date"),
        "payment_status": payload.get("payment_status"),
        "issues": issues,
        "evidence": payload.get("evidence") or {},
    }
    event.updated_at = _utcnow()
    if existing is None:
        session.add(event)
    return event
