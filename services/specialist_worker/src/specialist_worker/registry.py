from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from common.application.accounting import (
    project_accounting_result,
    reapply_manual_accounting_corrections,
)
from common.application.calendar import project_utility_bill_calendar_event
from common.application.payables import project_payable
from common.application.specialist_contracts import (
    SpecialistEvidence,
    SpecialistExecutionContext,
    SpecialistExtraction,
    SpecialistPresentation,
    SpecialistRegistry,
    SpecialistValidation,
)
from common.db.models import DocumentUnit, SpecialistResult
from knowledge_classifier.llm.base import LLMProvider
from sqlalchemy.orm import Session

from specialist_worker.services.accounting_statement import process_accounting_statement
from specialist_worker.services.utility_bill import process_utility_bill

MAX_AUTO_ACCEPTED_UTILITY_AMOUNT = Decimal("5000.00")


class UtilityBillHandler:
    capability = "utility_bill"
    schema_version = "utility_bill_v1"
    document_types = frozenset({"bolletta", "fattura"})

    def extract(self, context: SpecialistExecutionContext) -> SpecialistExtraction:
        payload, links, confidence = process_utility_bill(
            context.session, context.document_unit, context.text, context.input_version
        )
        payload["_source_checks"] = _utility_source_checks(payload, context.text)
        evidence = [
            SpecialistEvidence(
                field=field,
                page_from=context.document_unit.start_page,
                page_to=context.document_unit.end_page,
                raw_value=value,
            )
            for field, value in payload.items()
            if field not in {"evidence", "detail_link_candidates", "input_version"}
            and not isinstance(value, (dict, list))
            and value not in {None, "", "unknown"}
        ]
        return SpecialistExtraction(payload=payload, confidence=confidence, evidence=evidence, links=links)

    def validate(self, extraction: SpecialistExtraction) -> SpecialistValidation:
        required = ("issuer", "total_amount", "due_date")
        missing = tuple(field for field in required if extraction.payload.get(field) in {None, "", "unknown"})
        messages = [f"Missing recommended field: {field}" for field in missing]
        source_checks = extraction.payload.get("_source_checks") or {}
        for field in required:
            if field not in missing and source_checks.get(field) is not True:
                messages.append(f"Extracted field is not supported by source text: {field}")
        return SpecialistValidation(status="valid" if not messages else "needs_review", messages=tuple(messages))

    def project(self, session: Session, document_unit: DocumentUnit, result: SpecialistResult) -> None:
        project_payable(session, document_unit, result)
        project_utility_bill_calendar_event(session, document_unit, result)

    def present(self, payload: dict[str, Any]) -> SpecialistPresentation:
        return SpecialistPresentation(
            title="Bolletta o fattura",
            summary=payload.get("issuer"),
            fields=tuple(
                (label, payload.get(key))
                for label, key in (
                    ("Fornitore", "issuer"),
                    ("Oggetto", "service_type"),
                    ("Importo", "total_amount"),
                    ("Scadenza", "due_date"),
                )
                if payload.get(key) not in {None, "", "unknown"}
            ),
        )

    def reapply_corrections(self, payload: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        return payload


class AccountingStatementHandler:
    capability = "accounting_statement"
    schema_version = "accounting_statement_v6"
    document_types = frozenset({"rendiconto_contabile", "riparto_spese", "preventivo"})

    def __init__(self, provider_factory: Callable[[], LLMProvider | None]) -> None:
        self._provider_factory = provider_factory

    def extract(self, context: SpecialistExecutionContext) -> SpecialistExtraction:
        provider = self._provider_factory()
        try:
            payload, confidence = process_accounting_statement(
                context.document_unit,
                context.text,
                context.input_version,
                structured_json=context.structured_json,
                reconciliation_provider=provider,
            )
        finally:
            if provider is not None:
                provider.close()
        return SpecialistExtraction(
            payload=payload,
            confidence=confidence,
            evidence=_accounting_evidence(context.document_unit, payload),
        )

    def validate(self, extraction: SpecialistExtraction) -> SpecialistValidation:
        tables = extraction.payload.get("tables") or []
        checks = extraction.payload.get("validation_checks") or []
        failures = [check for check in checks if isinstance(check, dict) and check.get("status") == "fail"]
        messages: list[str] = []
        if not tables:
            messages.append("No accounting tables extracted.")
        if failures:
            messages.append(f"{len(failures)} deterministic validation checks failed.")
        return SpecialistValidation(
            status="valid" if tables and not failures else "needs_review",
            messages=tuple(messages),
        )

    def project(self, session: Session, document_unit: DocumentUnit, result: SpecialistResult) -> None:
        project_accounting_result(session, document_unit, result)

    def present(self, payload: dict[str, Any]) -> SpecialistPresentation:
        tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
        sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
        return SpecialistPresentation(
            title="Prospetto contabile",
            summary=payload.get("statement_type"),
            fields=(("Tabelle", len(tables)), ("Sezioni", len(sections))),
        )

    def reapply_corrections(self, payload: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        return reapply_manual_accounting_corrections(payload, previous)


def build_specialist_registry(
    accounting_provider_factory: Callable[[], LLMProvider | None],
) -> SpecialistRegistry:
    registry = SpecialistRegistry()
    registry.register(UtilityBillHandler())
    registry.register(AccountingStatementHandler(accounting_provider_factory))
    return registry


def _utility_source_checks(payload: dict[str, Any], text: str) -> dict[str, bool]:
    normalized_text = _normalized_search_text(text)
    return {
        "issuer": _issuer_supported(payload.get("issuer"), normalized_text),
        "total_amount": _amount_supported(payload.get("total_amount"), text),
        "due_date": _date_supported(payload.get("due_date"), normalized_text),
        "payment_reference": _literal_supported(payload.get("payment_reference"), normalized_text),
    }


def _normalized_search_text(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _literal_supported(value: Any, normalized_text: str) -> bool:
    normalized_value = _normalized_search_text(value)
    return not normalized_value or normalized_value in normalized_text


def _issuer_supported(value: Any, normalized_text: str) -> bool:
    tokens = [token for token in _normalized_search_text(value).split() if len(token) >= 3]
    if not tokens:
        return False
    matched = sum(token in normalized_text for token in tokens)
    return matched >= min(2, len(tokens)) and matched / len(tokens) >= 0.6


def _amount_supported(value: Any, text: str) -> bool:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return False
    if amount < 0 or amount > MAX_AUTO_ACCEPTED_UTILITY_AMOUNT:
        return False
    european = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    candidates = {f"{amount:.2f}", f"{amount:.2f}".replace(".", ","), european}
    compact_text = re.sub(r"\s+", "", text or "")
    return any(candidate in compact_text for candidate in candidates)


def _date_supported(value: Any, normalized_text: str) -> bool:
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(value or "").strip())
    if not match:
        return False
    year, month, day = match.groups()
    variants = (
        f"{day} {month} {year}",
        f"{day.lstrip('0') or '0'} {month.lstrip('0') or '0'} {year}",
        f"{year} {month} {day}",
    )
    return any(variant in normalized_text for variant in variants)


def _accounting_evidence(document_unit: DocumentUnit, payload: dict[str, Any]) -> list[SpecialistEvidence]:
    evidence: list[SpecialistEvidence] = []
    for field in ("statement_type", "accounting_period_from", "accounting_period_to", "currency"):
        value = payload.get(field)
        if value not in {None, "", "unknown"}:
            evidence.append(SpecialistEvidence(field, document_unit.start_page, document_unit.end_page, raw_value=value))
    for table in payload.get("tables") or []:
        if not isinstance(table, dict):
            continue
        page = table.get("page_number") if isinstance(table.get("page_number"), int) else document_unit.start_page
        headers = table.get("headers") if isinstance(table.get("headers"), list) else []
        for row in table.get("rows") or []:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells") if isinstance(row.get("cells"), dict) else {}
            for column in headers:
                value = cells.get(str(column))
                if value not in {None, ""}:
                    evidence.append(SpecialistEvidence(
                        field="table_cell", page_from=page, page_to=page,
                        table_id=str(table.get("table_id") or ""),
                        row_id=str(row.get("row_id") or ""), column_name=str(column), raw_value=value,
                    ))
    return evidence
