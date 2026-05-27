from __future__ import annotations

import json
from typing import Any, Literal

from knowledge_classifier.llm.base import ChatMessage, LLMProvider
from pydantic import BaseModel, Field


class AccountingHeaderCorrection(BaseModel):
    table_id: str
    original_header: str
    corrected_header: str
    reason: str


class AccountingCellCorrection(BaseModel):
    table_id: str
    row_id: str
    column: str
    original_value: str
    corrected_value: str
    reason: str


class AccountingTableInterpretation(BaseModel):
    table_id: str
    table_type: Literal[
        "expense_allocation",
        "payment_schedule",
        "summary",
        "balance",
        "unknown",
    ]
    reason: str


class AccountingReconciliationProposal(BaseModel):
    applicable: bool
    summary: str
    header_corrections: list[AccountingHeaderCorrection] = Field(default_factory=list)
    table_interpretations: list[AccountingTableInterpretation] = Field(default_factory=list)
    suspected_cell_corrections: list[AccountingCellCorrection] = Field(default_factory=list)


def propose_accounting_reconciliation(
    provider: LLMProvider,
    *,
    tables: list[dict[str, Any]],
    validation_checks: list[dict[str, Any]],
    trigger_reasons: list[str],
    segment_text: str,
) -> AccountingReconciliationProposal:
    prompt_payload = {
        "trigger_reasons": trigger_reasons,
        "validation_checks": validation_checks,
        "tables": [_compact_table(table) for table in tables],
        "nearby_document_text": segment_text[:2500],
    }
    messages = [
        ChatMessage(
            role="system",
            content=(
                "Sei un revisore di prospetti contabili condominiali estratti da OCR. "
                "Identifica esclusivamente interpretazioni strutturali supportate dal testo: "
                "tipo tabella e intestazioni semanticamente equivalenti. "
                "Non inventare righe o importi e non modificare automaticamente numeri. "
                "Se noti una probabile trascrizione errata in una cella, riportala soltanto in "
                "suspected_cell_corrections con valore originale, valore proposto e motivo; "
                "tale proposta richiedera revisione successiva."
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                "Proponi una riconciliazione strutturale per questo output di parsing. "
                "Usa soltanto table_id, row_id e intestazioni presenti nell'input. "
                "Se non vi sono correzioni solide imposta applicable=false.\n"
                + json.dumps(prompt_payload, ensure_ascii=True)
            ),
        ),
    ]
    parsed, _ = provider.chat_with_json(messages, AccountingReconciliationProposal)
    return AccountingReconciliationProposal.model_validate(parsed)


def _compact_table(table: dict[str, Any]) -> dict[str, Any]:
    rows = table.get("rows")
    sample_rows = rows[:8] if isinstance(rows, list) else []
    return {
        "table_id": table.get("table_id"),
        "table_type": table.get("table_type"),
        "headers": table.get("headers"),
        "raw_headers": table.get("raw_headers"),
        "rows": sample_rows,
        "totals": table.get("totals"),
        "accounting_context": table.get("accounting_context"),
    }
