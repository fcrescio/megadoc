from common.application.specialists import extract_document_unit_text, route_specialists_for_document_unit
from common.db.models import DocumentType, DocumentUnit, OCRResult


def _document_unit(start_page: int, end_page: int) -> DocumentUnit:
    return DocumentUnit(
        start_page=start_page,
        end_page=end_page,
        ordinal=1,
        review_status="auto_accepted",
    )


def test_extract_document_unit_text_uses_structured_page_boundaries():
    ocr_result = OCRResult(
        markdown_text="fallback page one\nfallback page two\nfallback page three",
        structured_json={
            "pages": [
                {"page_number": 1, "markdown": "Page one"},
                {"page_number": 2, "markdown": "Periodo: 01/07/2023 - 30/06/2024"},
                {"page_number": 3, "markdown": "Preventivo ripartizioni per unita"},
            ]
        },
        page_count=3,
    )

    text = extract_document_unit_text(_document_unit(2, 3), ocr_result)

    assert text == "Periodo: 01/07/2023 - 30/06/2024\nPreventivo ripartizioni per unita"


def test_extract_document_unit_text_falls_back_when_page_payload_is_incomplete():
    ocr_result = OCRResult(
        markdown_text="Page one\nPage two\nPage three",
        structured_json={"pages": [{"page_number": 1, "markdown": "Only page one"}]},
        page_count=3,
    )

    text = extract_document_unit_text(_document_unit(2, 3), ocr_result)

    assert text == "Page two\nPage three"


def test_route_specialists_does_not_treat_regulation_as_utility_bill():
    document_unit = _document_unit(1, 8)
    document_unit.document_type = DocumentType(code="regolamento_condominiale", name="Regolamento")
    document_unit.title = "Regolamento tecnico Acque S.p.A."
    document_unit.extracted_summary = "Regolamento del servizio idrico integrato e fornitura acqua"

    specialists = route_specialists_for_document_unit(
        document_unit,
        "acqua fornitura numero cliente totale bolletta servizio idrico integrato",
    )

    assert specialists == []


def test_route_specialists_accepts_real_utility_bill():
    document_unit = _document_unit(1, 1)
    document_unit.document_type = DocumentType(code="bolletta", name="Bolletta")
    document_unit.title = "Bolletta Acque"
    document_unit.extracted_summary = "Totale bolletta e data di emissione"

    specialists = route_specialists_for_document_unit(document_unit, "numero cliente rif.bolletta acqua")

    assert specialists == ["utility_bill"]
