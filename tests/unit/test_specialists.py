from common.application.specialists import extract_document_unit_text
from common.db.models import DocumentUnit, OCRResult


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
