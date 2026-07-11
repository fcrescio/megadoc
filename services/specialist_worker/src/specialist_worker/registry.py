from __future__ import annotations

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


class UtilityBillHandler:
    capability = "utility_bill"
    schema_version = "utility_bill_v1"
    document_types = frozenset({"bolletta", "fattura"})

    def extract(self, context: SpecialistExecutionContext) -> SpecialistExtraction:
        payload, links, confidence = process_utility_bill(
            context.session, context.document_unit, context.text, context.input_version
        )
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
        return SpecialistValidation(
            status="valid" if not missing else "needs_review",
            messages=tuple(f"Missing recommended field: {field}" for field in missing),
        )

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
