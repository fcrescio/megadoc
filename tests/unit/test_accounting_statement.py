from common.db.models import DocumentUnit
from specialist_worker.services.accounting_statement import process_accounting_statement


def _document_unit() -> DocumentUnit:
    return DocumentUnit(start_page=1, end_page=3, ordinal=1, review_status="auto_accepted")


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
