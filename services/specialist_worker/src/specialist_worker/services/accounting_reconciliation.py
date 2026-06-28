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


class AccountingTableExplanation(BaseModel):
    table_id: str
    summary: str = Field(
        description=(
            "Spiegazione specifica e concisa di cosa rappresenta la tabella, "
            "come leggere righe/colonne e quali limiti o incertezze considerare."
        )
    )
    role: str | None = Field(default=None, description="Ruolo semantico della tabella, se riconoscibile.")


class AccountingSummaryColumn(BaseModel):
    table_id: str
    source_header: str = Field(description="Intestazione esatta della colonna sorgente da usare.")
    label: str = Field(description="Etichetta breve e leggibile da mostrare nella sintesi.")
    role: Literal[
        "allocated_expense",
        "total",
        "balance",
        "payment",
        "installment",
        "millesimal_share",
        "other",
    ] = "allocated_expense"
    reason: str


class AccountingReconciliationProposal(BaseModel):
    applicable: bool
    summary: str
    header_corrections: list[AccountingHeaderCorrection] = Field(default_factory=list)
    table_interpretations: list[AccountingTableInterpretation] = Field(default_factory=list)
    table_explanations: list[AccountingTableExplanation] = Field(default_factory=list)
    summary_columns: list[AccountingSummaryColumn] = Field(default_factory=list)
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
                "Per ogni tabella fornisci anche una spiegazione specifica, utile a un utente umano "
                "per capire cosa sta leggendo e a un LLM per usarla come contesto. "
                "Inoltre proponi summary_columns: una selezione di colonne monetarie utili per creare "
                "una vista sintetica navigabile. Usa source_header esatti presenti nelle tabelle. "
                "Escludi colonne di soli millesimi, coefficienti, codici o conteggi salvo che siano indispensabili. "
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
                "Compila table_explanations per ogni tabella, anche se non proponi correzioni. "
                "Compila summary_columns con le colonne che un utente dovrebbe vedere nella sintesi Bilancio: "
                "spese generali, giardino, ascensore, riscaldamento, acqua, saldi, totali, rate o pagamenti "
                "quando presenti. Non usare intestazioni inventate in source_header; label invece deve essere leggibile. "
                "Se non vi sono correzioni solide imposta applicable=false, ma mantieni le spiegazioni.\n"
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
        "section_label": table.get("section_label"),
        "section_role": table.get("section_role"),
    }
