from types import SimpleNamespace

from scripts.evaluate_specialist_gold import _accounting_check, _normalized_page, _payable_comparisons
from specialist_worker.services.utility_bill import (
    _extract_account_holder,
    _extract_payment_reference,
    _extract_total_amount,
)


def test_payable_gold_comparison_normalizes_dates_amounts_and_names():
    comparisons = _payable_comparisons(
        {
            "payable_kind": "utility_bill",
            "issuer": "Toscana Energia Clienti S.p.A.",
            "recipient": "CRESCIOLI FRANCESCO",
            "due_date": "2009-03-05",
            "total_amount": 19.78,
            "currency": "EUR",
            "payment_reference": "170002460906000956",
        },
        {
            "payable_kind": "utility_bill",
            "issuer": "Toscana Energia",
            "recipient": "Francesco Crescioli",
            "due_date": "05/03/2009",
            "amount": "19,78",
            "currency": "EUR",
            "payment_reference": "170002460906000956",
        },
    )

    assert all(comparisons.values())


def test_amount_comparison_accepts_european_and_us_thousands_formats():
    comparisons = _payable_comparisons(
        {
            "payable_kind": "invoice", "issuer": "Issuer", "recipient": "Recipient",
            "due_date": "2026-01-01", "total_amount": "4,344.71", "currency": "EUR",
            "payment_reference": "INV-1",
        },
        {
            "payable_kind": "invoice", "issuer": "Issuer", "recipient": "Recipient",
            "due_date": "2026-01-01", "amount": "4344,71", "currency": "EUR",
            "payment_reference": "INV-1",
        },
    )

    assert comparisons["amount"] is True


def test_accounting_check_returns_cell_lineage():
    result = _accounting_check(
        [{
            "page_number": 3,
            "table_id": "table_1",
            "table_type": "statement",
            "headers": ["Voce", "Importo"],
            "rows": [{"row_id": "row_2", "cells": {"Voce": "Saldo finale", "Importo": "1.234,50"}}],
        }],
        {
            "page": 3,
            "table": "statement",
            "row": "Saldo finale",
            "column": "Importo",
            "expected": "1234.50",
            "comparison": "amount",
        },
    )

    assert result == {
        "matched": True,
        "page": 3,
        "table_id": "table_1",
        "row_id": "row_2",
        "column": "Importo",
        "actual": "1.234,50",
    }


def test_accounting_check_uses_human_table_label_as_soft_hint():
    result = _accounting_check(
        [{
            "page_number": 3,
            "table_id": "table_1",
            "headers": ["Voce", "Importo"],
            "rows": [{"row_id": "row_1", "cells": {"Voce": "Totale", "Importo": "20,00"}}],
        }],
        {
            "page": 3,
            "table": "Rendiconto generale",
            "row": "Totale",
            "column": "Importo",
            "expected": "20.00",
            "comparison": "amount",
        },
    )

    assert result["matched"] is True


def test_gold_pdf_page_is_mapped_to_reversed_ocr_order():
    ocr = SimpleNamespace(
        page_count=34,
        structured_json={"orientation_preprocess": {"page_order_reversed": True}},
    )

    assert _normalized_page(5, ocr) == 30
    assert _normalized_page(30, ocr) == 5


def test_accounting_check_matches_composite_row_identity_across_cells():
    result = _accounting_check(
        [{
            "page_number": 1,
            "table_id": "table_1",
            "headers": ["Data", "Causale", "Dare"],
            "rows": [{
                "row_id": "row_1",
                "cells": {"Data": "10 novembre 2008", "Causale": "Chiusura del conto", "Dare": "4.344,71"},
            }],
        }],
        {
            "page": 1,
            "row": "10 novembre 2008 / chiusura del conto",
            "column": "Dare",
            "expected": "4344.71",
            "comparison": "amount",
        },
    )

    assert result["matched"] is True


def test_payment_slip_fields_use_strong_labels():
    text = """Capitale sociale EUR 7.148.428,17
di Euro 19,78
ESEGUITO DA:
CRESCIOLI FRANCESCO
V CESARE STUDIATI 6
170002460906000956
"""

    assert _extract_total_amount(text) == 19.78
    assert _extract_account_holder(text) == "CRESCIOLI FRANCESCO"
    assert _extract_payment_reference(text) == "170002460906000956"


def test_payment_slip_amount_ignores_contractual_minimums():
    text = """La riapertura comporta un minimo di EURO 50,00.
Totale fattura salvo conguaglio Euro 104,86
"""

    assert _extract_total_amount(text) == 104.86
