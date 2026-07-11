from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import DocumentUnit, Payable, SpecialistResult


def project_payable(
    session: Session,
    document_unit: DocumentUnit,
    specialist_result: SpecialistResult,
) -> Payable | None:
    if specialist_result.specialist_type != "utility_bill":
        return None
    payload = specialist_result.result_json or {}
    payable_kind = str(payload.get("payable_kind") or _kind_from_document_unit(document_unit))
    issuer = _text(payload.get("issuer"))
    recipient = _text(payload.get("recipient") or payload.get("account_holder"))
    subject = _text(payload.get("subject") or payload.get("service_type") or payload.get("supply_reference"))
    issue_date = _date(payload.get("issue_date"))
    due_date = _date(payload.get("due_date"))
    amount = _amount(payload.get("total_amount"))
    currency = _text(payload.get("currency")) or "EUR"
    payment_reference = _text(
        payload.get("payment_reference")
        or payload.get("document_number")
        or payload.get("pod_pdr_or_supply_code")
    )
    status = str(payload.get("payment_status") or "unknown")
    fingerprint = payable_fingerprint(
        issuer=issuer,
        recipient=recipient,
        amount=amount,
        currency=currency,
        payment_reference=payment_reference,
        period_from=_text(payload.get("billing_period_from")),
        period_to=_text(payload.get("billing_period_to")),
    )
    issues = _review_issues(payable_kind, issuer, amount, due_date, payment_reference)
    review_status = (
        "auto_accepted"
        if not issues and (specialist_result.confidence or 0) >= 0.7
        else "needs_review"
    )

    payable = session.execute(
        select(Payable).where(Payable.source_specialist_result_id == specialist_result.id)
    ).scalar_one_or_none()
    if payable is None:
        payable = Payable(
            source_document_unit_id=document_unit.id,
            source_specialist_result_id=specialist_result.id,
            payable_kind=payable_kind,
            deduplication_fingerprint=fingerprint,
        )
        session.add(payable)
        session.flush()
    has_deduplication_identity = bool(
        issuer and amount is not None and (payment_reference or payload.get("billing_period_from") or payload.get("billing_period_to"))
    )
    duplicate = None
    if has_deduplication_identity:
        duplicate = session.execute(
            select(Payable)
            .where(
                Payable.deduplication_fingerprint == fingerprint,
                Payable.id != payable.id,
                Payable.duplicate_of_id.is_(None),
            )
            .order_by(Payable.created_at.asc())
            .limit(1)
        ).scalar_one_or_none()

    payable.source_document_unit_id = document_unit.id
    payable.duplicate_of_id = duplicate.id if duplicate else None
    payable.payable_kind = payable_kind
    payable.issuer = issuer
    payable.recipient = recipient
    payable.subject = subject
    payable.issue_date = issue_date
    payable.due_date = due_date
    payable.amount = amount
    payable.currency = currency
    payable.payment_reference = payment_reference
    payable.status = status
    payable.deduplication_fingerprint = fingerprint
    payable.confidence = specialist_result.confidence
    payable.review_status = "needs_review" if duplicate else review_status
    payable.evidence_json = {
        "issues": (["possible_duplicate"] if duplicate else []) + issues,
        "specialist_evidence": (payload.get("_specialist") or {}).get("evidence", []),
        "raw": {
            "issuer": payload.get("issuer"),
            "recipient": payload.get("recipient") or payload.get("account_holder"),
            "subject": payload.get("subject") or payload.get("service_type"),
            "issue_date": payload.get("issue_date"),
            "due_date": payload.get("due_date"),
            "amount": payload.get("total_amount"),
            "payment_reference": payment_reference,
        },
    }
    payable.updated_at = datetime.now(timezone.utc)
    session.flush()
    return payable


def payable_fingerprint(
    *, issuer: str | None, recipient: str | None, amount: Decimal | None,
    currency: str | None, payment_reference: str | None,
    period_from: str | None, period_to: str | None,
) -> str:
    identity = "|".join((
        _normalize(issuer), _normalize(recipient), str(amount or ""),
        _normalize(currency), _normalize(payment_reference),
        _normalize(period_from), _normalize(period_to),
    ))
    return hashlib.sha256(identity.encode()).hexdigest()


def _review_issues(
    payable_kind: str, issuer: str | None, amount: Decimal | None,
    due_date: date | None, payment_reference: str | None,
) -> list[str]:
    issues: list[str] = []
    if not issuer:
        issues.append("issuer_missing")
    if amount is None:
        issues.append("amount_missing_or_invalid")
    if payable_kind not in {"receipt"} and due_date is None:
        issues.append("due_date_missing")
    if not payment_reference:
        issues.append("payment_reference_missing")
    return issues


def _kind_from_document_unit(document_unit: DocumentUnit) -> str:
    code = document_unit.document_type.code if document_unit.document_type else ""
    return {"fattura": "invoice", "bolletta": "utility_bill"}.get(code, "payment_notice")


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10]) if value else None
    except ValueError:
        return None


def _amount(value: Any) -> Decimal | None:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01")) if value is not None else None
    except (InvalidOperation, ValueError):
        return None
    return amount if amount is not None and amount >= 0 else None


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()
