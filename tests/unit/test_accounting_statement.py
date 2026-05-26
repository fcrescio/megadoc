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
        "source": "document_unit",
        "review_status": "unverified",
    }
    assert general_expense["evidence"]["column"] == "Propr. Generale / Spese generali"

    total_due = next(fact for fact in account["facts"] if fact["fact_type"] == "amount_due")
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
