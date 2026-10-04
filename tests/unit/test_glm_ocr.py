import pytest

from common.config import Settings
from common.domain.exceptions import ProcessingError
from common.processing.glm_ocr import GLMOCRService, structured_glm_page, structured_sdk_page
from api.main import _ingestion_queue_for_backend


def test_glm_retains_table_html_and_page_evidence():
    markdown = 'Testo\n<table><tr><td rowspan="2">Acqua &amp; gas</td><td>12,30</td></tr></table>'
    page = structured_glm_page(3, markdown)
    assert page["markdown"] == markdown
    assert page["tables"][0]["page_number"] == 3
    assert page["tables"][0]["cells"][0]["html"] == markdown.split("\n")[1]
    assert _ingestion_queue_for_backend(Settings(OCR_BACKEND="glm_ocr"), None) == "ingestion_llm_vision"


def test_glm_rejects_truncated_generation(monkeypatch, valid_pdf_path):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"pages": [], "markdown": "partial"}

    monkeypatch.setattr("httpx.Client.post", lambda *args, **kwargs: Response())
    with pytest.raises(ProcessingError, match="exactly one page"):
        GLMOCRService(Settings()).process(valid_pdf_path)


def test_glm_markdown_table_becomes_structured_html():
    page = structured_glm_page(1, "Riparto\n\n| Unita | Acqua |\n|---|---|\n| A10 | 123,45 |")
    assert len(page["tables"]) == 1
    html = page["tables"][0]["cells"][0]["html"]
    assert "<td>A10</td>" in html
    assert "<td>123,45</td>" in html


def test_sdk_regions_keep_layout_and_table_evidence():
    html = '<table><tr><td rowspan="2">Acqua</td><td>12,30</td></tr></table>'
    page = structured_sdk_page(3, {"pages": [[{"label": "table", "native_label": "table", "bbox_2d": [10, 20, 900, 950], "content": html}]], "markdown": html})
    assert page["tables"][0]["page_number"] == 3
    assert page["tables"][0]["bbox"] == [10, 20, 900, 950]
    assert page["tables"][0]["cells"][0]["html"] == html
    assert page["blocks"][0]["type"] == "table"


def test_sdk_table_without_structure_is_not_silently_accepted():
    with pytest.raises(ValueError, match="no recoverable"):
        structured_sdk_page(1, {"pages": [[{"label": "table", "content": "flattened"}]], "markdown": "flattened"})
