from common.db.models import DocumentUnit
from specialist_worker.services.accounting_reconciliation import (
    AccountingCellCorrection,
    AccountingHeaderCorrection,
    AccountingReconciliationProposal,
    AccountingTableInterpretation,
)
from specialist_worker.services.accounting_statement import process_accounting_statement


def _document_unit() -> DocumentUnit:
    return DocumentUnit(start_page=1, end_page=3, ordinal=1, review_status="auto_accepted")


class _ReconciliationProvider:
    model_name = "fixture-accounting-model"
    provider_name = "fixture"

    def __init__(self, proposal: AccountingReconciliationProposal) -> None:
        self.proposal = proposal

    def chat_with_json(self, messages, schema, temperature=0.1, max_retries=3):
        return self.proposal, self.proposal.model_dump_json()


def test_accounting_statement_extracts_account_facts_with_evidence():
    text = """
Periodo: 01/07/2022 - 30/06/2023
| Unita | Nominativo | Propr. Generale / Spese generali | Totale gestione | Saldo finale |
| --- | --- | ---: | ---: | ---: |
| B11 | BONACCI FABIO | -362,59 | -1.419,21 | 636,41 |

| Nominativo | Unita | Importo | Data pag. |
| --- | --- | ---: | --- |
| BONACCI FABIO (B11) | B11 | 935,03 | 04/10/2022 |

| Nominativo | Unita | Totale dovuto | Rata n. 1 01/09/2023 | Rata n. 2 01/12/2023 |
| --- | --- | ---: | ---: | ---: |
| BONACCI FABIO | B11 (Pr) | 1.897,45 | 847,45 | 350,00 |
"""

    result, _ = process_accounting_statement(_document_unit(), text, "fixture:v1")

    account = next(account for account in result["accounts"] if account["unit_code"] == "B11")
    assert account["subject_label"] == "BONACCI FABIO"
    fact_types = {fact["fact_type"] for fact in account["facts"]}
    assert {"allocated_expense", "payment_received", "amount_due", "installment_due"} <= fact_types

    general_expense = next(
        fact
        for fact in account["facts"]
        if fact["category_key"] == "propr_generale_spese_generali"
    )
    assert general_expense["amount"] == 362.59
    assert general_expense["raw_amount"] == -362.59
    assert general_expense["period_context"] == {
        "from": "2022-07-01",
        "to": "2023-06-30",
        "source": "preceding_section",
        "review_status": "inferred",
    }
    assert general_expense["evidence"]["column"] == "Propr. Generale / Spese generali"

    total_due = next(fact for fact in account["facts"] if fact["fact_type"] == "amount_due")
    assert total_due["accounting_role"] == "budget_installment_schedule"
    assert total_due["amount"] == 1897.45
    assert total_due["evidence"]["raw_value"] == "1.897,45"


def test_accounting_statement_does_not_publish_unnamed_numeric_columns_as_facts():
    text = """
Periodo: 01/07/2022 - 30/06/2023
| Unita | Nominativo | column_7 | Mill. | Totale gestione |
| --- | --- | ---: | ---: | ---: |
| C28 | VAGAGGINI RICCARDO | -80,00 | 34,486 | -950,00 |
"""

    result, _ = process_accounting_statement(_document_unit(), text, "fixture:v1")

    account = result["accounts"][0]
    assert account["unit_code"] == "C28"
    assert [fact["category_key"] for fact in account["facts"]] == ["totale_gestione"]


def test_accounting_statement_keeps_currency_values_in_millesimal_headers():
    text = """
Consuntivo Ripartizioni per unita
Periodo: 01/07/2022 - 30/06/2023
| Unita | Nominativo | Spese generali / mill. | Riscaldamento / mill. | Ascensore / mill. | Totale gestione / mill. |
| --- | --- | ---: | ---: | ---: | ---: |
| B11 | BONACCI FABIO | -362,59 | 121,2958 | 0,00 | -1.419,21 |
"""

    result, _ = process_accounting_statement(_document_unit(), text, "fixture:v5")

    account = result["accounts"][0]
    categories = {fact["category_key"]: fact["amount"] for fact in account["facts"]}
    assert categories["spese_generali_mill"] == 362.59
    assert categories["totale_gestione"] == 1419.21
    assert "riscaldamento_mill" not in categories
    assert "ascensore_mill" not in categories


def test_accounting_statement_scopes_period_and_role_to_each_section():
    text = """
Consuntivo Ripartizioni per unita
Periodo: 01/07/2022 - 30/06/2023
| Unita | Nominativo | Totale gestione | Rate versate | Saldo finale |
| --- | --- | ---: | ---: | ---: |
| B11 | BONACCI FABIO | -1.419,21 | -2.030,41 | 636,41 |

Preventivo ripartizioni per unita
Periodo: 01/07/2023 - 30/06/2024
| Nominativo | Unita | Totale preventivo | Rata n. 1 01/09/2023 | Totale dovuto |
| --- | --- | ---: | ---: | ---: |
| BONACCI FABIO | B11 (Pr) | -1.897,45 | 847,45 | 1.897,45 |
"""

    result, _ = process_accounting_statement(_document_unit(), text, "fixture:v2")

    facts = result["accounts"][0]["facts"]
    closing_balance = next(fact for fact in facts if fact["fact_type"] == "closing_balance")
    due = next(fact for fact in facts if fact["fact_type"] == "amount_due")

    assert closing_balance["accounting_role"] == "actual_allocation"
    assert closing_balance["period_context"]["from"] == "2022-07-01"
    assert due["accounting_role"] == "budget_installment_schedule"
    assert due["period_context"] == {
        "from": "2023-07-01",
        "to": "2024-06-30",
        "source": "preceding_section",
        "review_status": "inferred",
    }


def test_accounting_statement_groups_composite_condominium_sections():
    text = """
Rendiconto consuntivo gestione
Periodo: 01/07/2022 - 30/06/2023
| Voce | Importo |
| --- | ---: |
| Entrate ordinarie | 10.000,00 |

Consuntivo ripartizioni per unita
Periodo: 01/07/2022 - 30/06/2023
| Unita | Nominativo | Totale gestione | Saldo finale |
| --- | --- | ---: | ---: |
| B11 | BONACCI FABIO | -1.419,21 | 636,41 |

Bilancio preventivo gestione
Periodo: 01/07/2023 - 30/06/2024
| Voce | Importo |
| --- | ---: |
| Spese generali | 10.000,00 |

Preventivo ripartizioni per unita
Periodo: 01/07/2023 - 30/06/2024
| Unita | Nominativo | Totale preventivo |
| --- | --- | ---: |
| B11 | BONACCI FABIO | -1.897,45 |

RATE DA VERSARE alle scadenze indicate
Periodo: 01/07/2023 - 30/06/2024
| Nominativo | Unita | Totale dovuto | Rata n. 1 01/09/2023 |
| --- | --- | ---: | ---: |
| BONACCI FABIO | B11 (Pr) | 1.897,45 | 847,45 |
"""

    result, _ = process_accounting_statement(_document_unit(), text, "fixture:v7")

    assert result["statement_type"] == "rendiconto_composito"
    labels = [section["label"] for section in result["sections"]]
    assert "Rendiconto / consuntivo" in labels
    assert "Riparto consuntivo" in labels
    assert "Preventivo" in labels
    assert "Riparto preventivo" in labels
    assert "Rate da versare" in labels
    assert all(table.get("section_id") for table in result["tables"])


def test_accounting_statement_locates_context_for_structured_table():
    html = (
        "<table><thead><tr><th>Unita</th><th>Nominativo</th><th>Totale gestione</th>"
        "<th>Saldo finale</th></tr></thead><tbody><tr><td>B11</td><td>BONACCI FABIO</td>"
        "<td>-1.419,21</td><td>636,41</td></tr></tbody></table>"
    )
    text = f"Consuntivo Ripartizioni per unita\nPeriodo: 01/07/2022 - 30/06/2023\n{html}"
    structured_json = {
        "tables": [{"self_ref": "#/tables/table_1", "cells": [{"html": html}], "page_number": 1}]
    }

    result, _ = process_accounting_statement(
        _document_unit(),
        text,
        "fixture:v3",
        structured_json=structured_json,
    )

    fact = next(
        fact
        for fact in result["accounts"][0]["facts"]
        if fact["fact_type"] == "closing_balance"
    )
    assert fact["accounting_role"] == "actual_allocation"
    assert fact["period_context"]["review_status"] == "inferred"


def test_accounting_statement_classifies_booked_personal_charges_as_actual():
    text = """
Periodo: 01/07/2022 - 30/06/2023
| Movimento | Importo |
| --- | ---: |
| - B11 BONACCI FABIO - 31/01/23 - (P13) - Riparazione citofono | -155,66 |
"""

    result, _ = process_accounting_statement(_document_unit(), text, "fixture:v4")

    fact = result["accounts"][0]["facts"][0]
    assert fact["fact_type"] == "personal_charge"
    assert fact["accounting_role"] == "actual_personal_charge"


def test_accounting_statement_uses_llm_header_reconciliation_only_when_it_improves_extraction():
    text = """
Consuntivo Ripartizioni per unita
Periodo: 01/07/2022 - 30/06/2023
| Unita | Nominativo | Sp. gen. | Tot. gest. |
| --- | --- | ---: | ---: |
| B11 | BONACCI FABIO | -60,00 | -60,00 |
"""
    provider = _ReconciliationProvider(
        AccountingReconciliationProposal(
            applicable=True,
            summary="Intestazioni OCR non riconosciute.",
            header_corrections=[
                AccountingHeaderCorrection(
                    table_id="table_1",
                    original_header="Sp. gen.",
                    corrected_header="Spese generali",
                    reason="Voce di riparto leggibile nel prospetto.",
                ),
                AccountingHeaderCorrection(
                    table_id="table_1",
                    original_header="Tot. gest.",
                    corrected_header="Totale gestione",
                    reason="Colonna totale del prospetto.",
                ),
            ],
        )
    )

    result, _ = process_accounting_statement(
        _document_unit(),
        text,
        "fixture:v6",
        reconciliation_provider=provider,
    )

    facts = result["accounts"][0]["facts"]
    assert {fact["category_key"] for fact in facts} == {"spese_generali", "totale_gestione"}
    assert result["reconciliation"]["status"] == "applied_structural"
    assert result["reconciliation"]["model"] == "fixture-accounting-model"


def test_accounting_statement_keeps_suspected_numeric_corrections_pending_review():
    text = """
Consuntivo Ripartizioni per unita
Periodo: 01/07/2022 - 30/06/2023
| Unita | Nominativo | Sp. gen. | Tot. gest. |
| --- | --- | ---: | ---: |
| B11 | BONACCI FABIO | -60,00 | -60,00 |
| B12 | ROSSI MARIO | -40,00 | -4O,00 |
"""
    provider = _ReconciliationProvider(
        AccountingReconciliationProposal(
            applicable=True,
            summary="Riconosciuta una voce; totale contiene un carattere ambiguo.",
            header_corrections=[
                AccountingHeaderCorrection(
                    table_id="table_1",
                    original_header="Sp. gen.",
                    corrected_header="Spese generali",
                    reason="Voce contabile leggibile.",
                ),
                AccountingHeaderCorrection(
                    table_id="table_1",
                    original_header="Tot. gest.",
                    corrected_header="Totale gestione",
                    reason="Colonna totale leggibile.",
                ),
            ],
            suspected_cell_corrections=[
                AccountingCellCorrection(
                    table_id="table_1",
                    row_id="row_2",
                    column="Tot. gest.",
                    original_value="-4O,00",
                    corrected_value="-40,00",
                    reason="Possibile O al posto di zero.",
                )
            ],
        )
    )

    result, _ = process_accounting_statement(
        _document_unit(),
        text,
        "fixture:v6",
        reconciliation_provider=provider,
    )

    row = result["tables"][0]["rows"][1]
    assert row["cells"]["Totale gestione"] == "-4O,00"
    assert result["reconciliation"]["status"] == "applied_with_pending_review"
    assert result["reconciliation"]["suspected_cell_corrections"][0]["corrected_value"] == "-40,00"


def test_accounting_statement_rejects_semantics_invented_for_unnamed_columns():
    text = """
Consuntivo Ripartizioni per unita
Periodo: 01/07/2022 - 30/06/2023
| Unita | Nominativo | column_3 |
| --- | --- | ---: |
| B11 | BONACCI FABIO | -60,00 |
"""
    provider = _ReconciliationProvider(
        AccountingReconciliationProposal(
            applicable=True,
            summary="Colonna senza etichetta.",
            header_corrections=[
                AccountingHeaderCorrection(
                    table_id="table_1",
                    original_header="column_3",
                    corrected_header="Spese generali",
                    reason="Interpretazione non verificabile.",
                )
            ],
        )
    )

    result, _ = process_accounting_statement(
        _document_unit(),
        text,
        "fixture:v6",
        reconciliation_provider=provider,
    )

    assert result["accounts"] == []
    assert result["reconciliation"]["status"] == "rejected"


def test_accounting_statement_rejects_unsupported_table_interpretation():
    text = """
Periodo: 01/07/2022 - 30/06/2023
| Descrizione | Importo |
| --- | ---: |
| Costi non attribuiti | -60,00 |
"""
    provider = _ReconciliationProvider(
        AccountingReconciliationProposal(
            applicable=True,
            summary="Interpretazione non sostenuta da righe soggetto.",
            table_interpretations=[
                AccountingTableInterpretation(
                    table_id="table_1",
                    table_type="expense_allocation",
                    reason="Proposta priva di unita o nominativo.",
                )
            ],
        )
    )

    result, _ = process_accounting_statement(
        _document_unit(),
        text,
        "fixture:v6",
        reconciliation_provider=provider,
    )

    assert result["tables"][0]["table_type"] == "unknown"
    assert result["reconciliation"]["status"] == "rejected"


def test_accounting_statement_does_not_request_reconciliation_without_provider():
    text = """
Periodo: 01/07/2022 - 30/06/2023
| Unita | Nominativo | column_3 |
| --- | --- | ---: |
| B11 | BONACCI FABIO | -60,00 |
"""

    result, _ = process_accounting_statement(_document_unit(), text, "fixture:v6")

    assert result["accounts"] == []
    assert result["reconciliation"]["status"] == "not_requested"
    assert "unnamed_columns_present" in result["reconciliation"]["trigger_reasons"]
