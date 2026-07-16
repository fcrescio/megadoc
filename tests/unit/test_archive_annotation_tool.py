from pathlib import Path

from scripts.archive_annotation_server import (
    accounting_tables_from_ocr,
    annotation_progress,
    empty_annotations,
    fetch_accounting_tables,
    load_annotations,
    normalize_annotations,
    normalize_page_spec,
    parse_html_gold_table,
    parse_legacy_accounting_checks,
    save_annotations,
)
from scripts.validate_archive_annotations import validate_annotations


def _case(case_id: str = "case-1", pages: int = 2):
    return {"case_id": case_id, "pages": pages}


def test_annotation_save_is_round_trip(tmp_path: Path):
    path = tmp_path / "annotations.json"
    payload = empty_annotations()
    payload["documents"] = {"case-1": {"reviewed": True}}

    save_annotations(path, payload)
    loaded = load_annotations(path)

    assert loaded["documents"]["case-1"]["reviewed"] is True
    assert loaded["updated_at"]
    assert not list(tmp_path.glob(".annotations.json.*"))


def test_progress_counts_review_and_specialists():
    payload = empty_annotations()
    payload["documents"] = {
        "case-1": {
            "reviewed": True,
            "document_units": [{
                "start_page": 1,
                "end_page": 2,
                "specialist": {"kind": "payable"},
            }],
        }
    }
    payload["questions"] = [{"question": "Q"}]

    progress = annotation_progress([_case()], payload)

    assert progress["documents_reviewed"] == 1
    assert progress["document_units"] == 1
    assert progress["payable_cases"] == 1
    assert progress["questions"] == 1


def test_legacy_annotations_are_migrated_and_reopened_for_review():
    payload = empty_annotations()
    payload["documents"] = {
        "case-1": {
            "reviewed": True,
            "document_type": "rendiconto_contabile",
            "title": "Rendiconto",
            "entities": ["Condominio Roma"],
            "document_units": [],
            "specialist": {"kind": "none"},
        }
    }

    normalized = normalize_annotations([_case()], payload)
    document = normalized["documents"]["case-1"]

    assert document["reviewed"] is False
    assert document["entities"] == [{"entity_type": "unknown", "value": "Condominio Roma"}]
    assert document["document_units"][0]["start_page"] == 1
    assert document["document_units"][0]["end_page"] == 2
    assert document["document_units"][0]["specialist"]["kind"] == "accounting"
    assert "specialist" not in document


def test_strict_validator_accepts_complete_fixture():
    cases = [_case(f"case-{index}", 2) for index in range(1, 21)]
    payload = empty_annotations()
    for index, case in enumerate(cases, start=1):
        kind = "payable" if index <= 10 else "accounting"
        specialist = (
            {"kind": kind, "payable_kind": "invoice", "issuer": "Issuer", "amount": "10",
             "currency": "EUR", "due_date": "2026-01-01", "payment_reference": "INV-1"}
            if kind == "payable"
            else {"kind": kind, "table_pages": "1-2", "checks": [{
                "page": 1, "table": "Rendiconto", "row": "Totale", "column": "Importo",
                "expected": "10", "comparison": "amount",
            }], "tables_reviewed": True, "gold_tables": [{
                "page_number": 1,
                "title": "Rendiconto",
                "headers": ["Voce", "Importo"],
                "rows": [{"row_id": "gold_row_1", "cells": {"Voce": "Totale", "Importo": "10"}}],
            }]}
        )
        payload["documents"][case["case_id"]] = {
            "reviewed": True,
            "orientation_verified": True,
            "document_type": "fattura" if kind == "payable" else "rendiconto_contabile",
            "title": case["case_id"],
            "entities": [{"entity_type": "organizzazione", "value": "Fixture"}],
            "document_units": [{
                "start_page": 1, "end_page": 2,
                "document_type": "fattura" if kind == "payable" else "rendiconto_contabile",
                "title": case["case_id"],
                "specialist": specialist,
            }],
        }
    payload["questions"] = [
        {"question": f"Question {index}", "answerable": True,
         "expected_answer": "Answer", "evidence": "case-1:1"}
        for index in range(30)
    ]

    report = validate_annotations(cases, payload)

    assert report["valid"], report


def test_accounting_legacy_checks_are_structured_and_relative_pages_become_absolute():
    checks = parse_legacy_accounting_checks(
        "pg. 1 | Situazione contabile | Saldo | Importo | 10,50",
        start_page=16,
        end_page=16,
    )

    assert checks == [{
        "page": 16,
        "table": "Situazione contabile",
        "row": "Saldo",
        "column": "Importo",
        "expected": "10,50",
        "comparison": "amount",
    }]
    assert normalize_page_spec("1", start_page=16, end_page=16) == [16]


def test_specialist_schema_upgrade_reopens_review_for_full_gold_tables():
    payload = empty_annotations()
    payload["documents"] = {
        "case-1": {
            "reviewed": True,
            "entities": [],
            "document_units": [{
                "start_page": 1,
                "end_page": 2,
                "document_type": "rendiconto_contabile",
                "specialist": {
                    "kind": "accounting",
                    "table_pages": "1",
                    "cell_checks": "p.1 | Rendiconto | Totale | Importo | 10,00",
                },
            }],
        }
    }

    document = normalize_annotations([_case()], payload)["documents"]["case-1"]

    assert document["reviewed"] is False
    assert document["document_units"][0]["specialist"]["gold_tables"] == []
    assert document["document_units"][0]["specialist"]["tables_reviewed"] is False
    assert document["document_units"][0]["specialist"]["checks"][0]["expected"] == "10,00"


def test_specialist_schema_upgrade_reopens_incomplete_accounting_checks():
    payload = empty_annotations()
    payload["documents"] = {
        "case-1": {
            "reviewed": True,
            "entities": [],
            "document_units": [{
                "start_page": 1,
                "end_page": 1,
                "document_type": "rendiconto_contabile",
                "specialist": {
                    "kind": "accounting",
                    "table_pages": "1",
                    "checks": [{"page": 1, "row": "Totale", "column": "Importo", "expected": ""}],
                },
            }],
        }
    }

    document = normalize_annotations([_case(pages=1)], payload)["documents"]["case-1"]

    assert document["reviewed"] is False


def test_fetch_accounting_tables_resolves_external_id(monkeypatch):
    responses = iter([
        [{"id": "doc-1", "external_id": "case-1"}],
        {"document_id": "doc-1", "tables": [{"table_id": "table_1"}]},
    ])
    urls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            import json
            return json.dumps(self.payload).encode()

    def fake_urlopen(url, timeout):
        urls.append((url, timeout))
        return Response(next(responses))

    monkeypatch.setattr("scripts.archive_annotation_server.urllib.request.urlopen", fake_urlopen)

    result = fetch_accounting_tables("http://api:8080/", "case-1")

    assert result["status"] == "available"
    assert result["tables"] == [{"table_id": "table_1"}]
    assert urls == [
        ("http://api:8080/documents", 15),
        ("http://api:8080/knowledge/documents/doc-1/accounting-raw-tables", 30),
    ]


def test_parse_html_gold_table_preserves_full_editable_matrix():
    parsed = parse_html_gold_table(
        "<table><thead><tr><th>Data</th><th colspan='2'>Importi</th></tr></thead>"
        "<tbody><tr><td>20 maggio</td><td>10,00</td><td>2,00</td></tr></tbody></table>"
    )

    assert parsed == (
        ["Data", "Importi", "Colonna 3"],
        [{
            "row_id": "row_1",
            "cells": {"Data": "20 maggio", "Importi": "10,00", "Colonna 3": "2,00"},
        }],
    )


def test_accounting_tables_from_ocr_maps_reversed_pages_to_source_pdf():
    tables = accounting_tables_from_ocr({
        "page_count": 3,
        "structured_json": {
            "orientation_preprocess": {"page_order_reversed": True},
            "pages": [{
                "page_number": 3,
                "tables": [{
                    "id": "page-3-table-1",
                    "cells": [{"html": "<table><tr><th>Voce</th><th>Importo</th></tr><tr><td>Totale</td><td>10,00</td></tr></table>"}],
                }],
            }],
        },
    })

    assert len(tables) == 1
    assert tables[0]["page_number"] == 1
    assert tables[0]["headers"] == ["Voce", "Importo"]
    assert tables[0]["rows"][0]["cells"]["Importo"] == "10,00"
